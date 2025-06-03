import re
import requests
import logging
from collections import OrderedDict
from datetime import datetime
import concurrent.futures
import config
import os
import difflib

# 输出目录
output_folder = "output"
os.makedirs(output_folder, exist_ok=True)

# 日志设置
log_file_path = os.path.join(output_folder, "function.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_file_path, "w", encoding="utf-8"), logging.StreamHandler()],
)

def parse_template(template_file):
    """解析模板文件，提取频道分类和频道名称"""
    template_channels = OrderedDict()
    current_category = None
    with open(template_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if "#genre#" in line:
                    current_category = line.split(",")[0].strip()
                    template_channels[current_category] = []
                elif current_category:
                    channel_name = line.split(",")[0].strip()
                    template_channels[current_category].append(channel_name)
    return template_channels

def clean_channel_name(channel_name):
    cleaned_name = re.sub(r'[$「」-]', '', channel_name)
    cleaned_name = re.sub(r'\s+', '', cleaned_name)
    cleaned_name = re.sub(r'(\D*)(\d+)', lambda m: m.group(1) + str(int(m.group(2))), cleaned_name)
    return cleaned_name.upper()

def fetch_channels(url):
    """从URL抓取频道列表，支持m3u和txt"""
    channels = OrderedDict()
    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
        response.encoding = 'utf-8'
        lines = response.text.split("\n")
        is_m3u = any(line.startswith("#EXTINF") for line in lines[:15])
        source_type = "m3u" if is_m3u else "txt"
        logging.info(f"url: {url} 成功，判断为{source_type}格式")
        if is_m3u:
            channels.update(parse_m3u_lines(lines))
        else:
            channels.update(parse_txt_lines(lines))
        if channels:
            categories = ", ".join(channels.keys())
            logging.info(f"url: {url} 成功，包含频道分类: {categories}")
    except requests.RequestException as e:
        logging.error(f"url: {url} 失败❌, Error: {e}")
    return channels

def parse_m3u_lines(lines):
    channels = OrderedDict()
    current_category = None
    channel_name = None
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF"):
            match = re.search(r'group-title="(.*?)",(.*)', line)
            if match:
                current_category = match.group(1).strip()
                channel_name = match.group(2).strip()
                if channel_name:
                    channel_name = clean_channel_name(channel_name)
                if current_category not in channels:
                    channels[current_category] = []
        elif line and not line.startswith("#"):
            channel_url = line.strip()
            if current_category and channel_name:
                channels[current_category].append((channel_name, channel_url))
    return channels

def parse_txt_lines(lines):
    channels = OrderedDict()
    current_category = None
    for line in lines:
        line = line.strip()
        if "#genre#" in line:
            current_category = line.split(",")[0].strip()
            channels[current_category] = []
        elif current_category:
            match = re.match(r"^(.*?),(.*?)$", line)
            if match:
                channel_name = match.group(1).strip()
                if channel_name:
                    channel_name = clean_channel_name(channel_name)
                channel_urls = match.group(2).strip().split('#')
                for channel_url in channel_urls:
                    channel_url = channel_url.strip()
                    channels[current_category].append((channel_name, channel_url))
            elif line:
                channels[current_category].append((line, ''))
    return channels

def find_similar_name(target_name, name_list):
    matches = difflib.get_close_matches(target_name, name_list, n=1, cutoff=0.6)
    return matches[0] if matches else None

def match_channels(template_channels, all_channels):
    matched_channels = OrderedDict()
    all_online_channel_names = []
    for online_category, online_channel_list in all_channels.items():
        for online_channel_name, _ in online_channel_list:
            all_online_channel_names.append(online_channel_name)
    for category, channel_list in template_channels.items():
        matched_channels[category] = OrderedDict()
        for channel_name in channel_list:
            similar_name = find_similar_name(channel_name, all_online_channel_names)
            if similar_name:
                for online_category, online_channel_list in all_channels.items():
                    for online_channel_name, online_channel_url in online_channel_list:
                        if online_channel_name == similar_name:
                            matched_channels[category].setdefault(channel_name, []).append(online_channel_url)
    return matched_channels

def filter_source_urls(template_file):
    template_channels = parse_template(template_file)
    source_urls = config.source_urls
    all_channels = OrderedDict()
    for url in source_urls:
        fetched_channels = fetch_channels(url)
        merge_channels(all_channels, fetched_channels)
    matched_channels = match_channels(template_channels, all_channels)
    return matched_channels, template_channels

def merge_channels(target, source):
    for category, channel_list in source.items():
        if category in target:
            target[category].extend(channel_list)
        else:
            target[category] = channel_list

def is_ipv6(url):
    return re.match(r'^http:\/\/\[[0-9a-fA-F:]+\]', url) is not None

def test_url_speed(url, timeout=3):
    """测速单个URL，失败或超时返回极大值"""
    try:
        resp = requests.head(url, timeout=timeout)
        if resp.status_code == 200:
            return url, resp.elapsed.total_seconds()
    except Exception:
        pass
    return url, float('inf')

def get_best_urls(url_list, max_count=3, timeout=3):
    """多线程测速，返回最快的max_count个url"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda u: test_url_speed(u, timeout), url_list))
    available = [r for r in results if r[1] != float('inf')]
    available.sort(key=lambda x: x[1])
    return [u for u, _ in available[:max_count]]

def add_url_suffix(url, index, total_urls, ip_version):
    suffix = f"${ip_version}" if total_urls == 1 else f"${ip_version}•线路{index}"
    base_url = url.split('$', 1)[0] if '$' in url else url
    return f"{base_url}{suffix}"

def write_to_files(f_m3u, f_txt, category, channel_name, index, new_url):
    logo_url = f"./pic/logos{channel_name}.png"
    f_m3u.write(f'#EXTINF:-1 tvg-id="{index}" tvg-name="{channel_name}" tvg-logo="{logo_url}" group-title="{category}",{channel_name}\n')
    f_m3u.write(new_url + "\n")
    f_txt.write(f"{channel_name},{new_url}\n")

def updateChannelUrlsM3U(channels, template_channels):
    written_urls_ipv4 = set()
    written_urls_ipv6 = set()
    current_date = datetime.now().strftime("%Y-%m-%d")
    for group in config.announcements:
        for announcement in group['entries']:
            if announcement['name'] is None:
                announcement['name'] = current_date

    ipv4_m3u_path = os.path.join(output_folder, "live_ipv4.m3u")
    ipv4_txt_path = os.path.join(output_folder, "live_ipv4.txt")
    ipv6_m3u_path = os.path.join(output_folder, "live_ipv6.m3u")
    ipv6_txt_path = os.path.join(output_folder, "live_ipv6.txt")

    with open(ipv4_m3u_path, "w", encoding="utf-8") as f_m3u_ipv4, \
        open(ipv4_txt_path, "w", encoding="utf-8") as f_txt_ipv4, \
        open(ipv6_m3u_path, "w", encoding="utf-8") as f_m3u_ipv6, \
        open(ipv6_txt_path, "w", encoding="utf-8") as f_txt_ipv6:

        # 写入EPG
        f_m3u_ipv4.write(f'#EXTM3U x-tvg-url={",".join([f\'"{epg_url}"\' for epg_url in config.epg_urls])}\n')
        f_m3u_ipv6.write(f'#EXTM3U x-tvg-url={",".join([f\'"{epg_url}"\' for epg_url in config.epg_urls])}\n')

        # 写入公告
        for group in config.announcements:
            f_txt_ipv4.write(f"{group['channel']},#genre#\n")
            f_txt_ipv6.write(f"{group['channel']},#genre#\n")
            for announcement in group['entries']:
                url = announcement['url']
                if is_ipv6(url):
                    if url not in written_urls_ipv6:
                        written_urls_ipv6.add(url)
                        f_m3u_ipv6.write(f'#EXTINF:-1 tvg-id="1" tvg-name="{announcement["name"]}" tvg-logo="{announcement["logo"]}" group-title="{group["channel"]}",{announcement["name"]}\n')
                        f_m3u_ipv6.write(f"{url}\n")
                        f_txt_ipv6.write(f"{announcement['name']},{url}\n")
                else:
                    if url not in written_urls_ipv4:
                        written_urls_ipv4.add(url)
                        f_m3u_ipv4.write(f'#EXTINF:-1 tvg-id="1" tvg-name="{announcement["name"]}" tvg-logo="{announcement["logo"]}" group-title="{group["channel"]}",{announcement["name"]}\n')
                        f_m3u_ipv4.write(f"{url}\n")
                        f_txt_ipv4.write(f"{announcement['name']},{url}\n")

        # 写入频道
        for category, channel_list in template_channels.items():
            f_txt_ipv4.write(f"{category},#genre#\n")
            f_txt_ipv6.write(f"{category},#genre#\n")
            if category in channels:
                for channel_name in channel_list:
                    if channel_name in channels[category]:
                        urls = channels[category][channel_name]
                        # 多线程测速优选
                        best_urls = get_best_urls(urls, max_count=3, timeout=3)
                        sorted_urls_ipv4 = [u for u in best_urls if not is_ipv6(u) and u not in written_urls_ipv4]
                        sorted_urls_ipv6 = [u for u in best_urls if is_ipv6(u) and u not in written_urls_ipv6]
                        total_ipv4 = len(sorted_urls_ipv4)
                        total_ipv6 = len(sorted_urls_ipv6)
                        for idx, url in enumerate(sorted_urls_ipv4, 1):
                            written_urls_ipv4.add(url)
                            new_url = add_url_suffix(url, idx, total_ipv4, "IPV4")
                            write_to_files(f_m3u_ipv4, f_txt_ipv4, category, channel_name, idx, new_url)
                        for idx, url in enumerate(sorted_urls_ipv6, 1):
                            written_urls_ipv6.add(url)
                            new_url = add_url_suffix(url, idx, total_ipv6, "IPV6")
                            write_to_files(f_m3u_ipv6, f_txt_ipv6, category, channel_name, idx, new_url)

        f_txt_ipv4.write("\n")
        f_txt_ipv6.write("\n")

if __name__ == "__main__":
    template_file = "demo.txt"
    channels, template_channels = filter_source_urls(template_file)
    updateChannelUrlsM3U(channels, template_channels)
