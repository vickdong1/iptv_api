import re
import requests
import logging
from collections import OrderedDict
from datetime import datetime
import config
import os
import difflib
import time

# 确保 output 文件夹存在
output_folder = "output"
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

# 日志记录，将日志文件保存到 output 文件夹下
log_file_path = os.path.join(output_folder, "function.log")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler(log_file_path, "w", encoding="utf-8"), logging.StreamHandler()])

def parse_template(template_file):
    """
    解析模板文件，提取频道分类和频道名称。
    :param template_file: 模板文件路径
    :return: 包含频道分类和频道名称的有序字典
    """
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
    """
    清洗频道名称，去除特定字符并转换为大写。
    :param channel_name: 原始频道名称
    :return: 清洗后的频道名称
    """
    cleaned_name = re.sub(r'[$「」-]', '', channel_name)
    cleaned_name = re.sub(r'\s+', '', cleaned_name)
    cleaned_name = re.sub(r'(\D*)(\d+)', lambda m: m.group(1) + str(int(m.group(2))), cleaned_name)
    return cleaned_name.upper()

def fetch_channels(url):
    """
    从指定URL抓取频道列表。
    :param url: 频道列表的URL
    :return: 包含频道分类和频道信息的有序字典
    """
    channels = OrderedDict()
    try:
        response = requests.get(url)
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
    """
    解析M3U格式的频道列表行。
    :param lines: M3U文件的行列表
    :return: 包含频道分类和频道信息的有序字典
    """
    channels = OrderedDict()
    current_category = None
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF"):
            match = re.search(r'group-title="(.*?)",(.*)', line)
            if match:
                current_category = match.group(1).strip()
                channel_name = match.group(2).strip()
                if channel_name and channel_name.startswith("CCTV"):
                    channel_name = clean_channel_name(channel_name)
                if current_category not in channels:
                    channels[current_category] = []
        elif line and not line.startswith("#"):
            channel_url = line.strip()
            if current_category and channel_name:
                channels[current_category].append((channel_name, channel_url))
    return channels

def parse_txt_lines(lines):
    """
    解析TXT格式的频道列表行。
    :param lines: TXT文件的行列表
    :return: 包含频道分类和频道信息的有序字典
    """
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
                if channel_name and channel_name.startswith("CCTV"):
                    channel_name = clean_channel_name(channel_name)
                channel_urls = match.group(2).strip().split('#')
                for channel_url in channel_urls:
                    channel_url = channel_url.strip()
                    channels[current_category].append((channel_name, channel_url))
            elif line:
                channels[current_category].append((line, ''))
    return channels

def find_similar_name(target_name, name_list):
    """
    查找最相似的名称。
    :param target_name: 目标名称
    :param name_list: 名称列表
    :return: 最相似的名称，如果没有则返回None
    """
    matches = difflib.get_close_matches(target_name, name_list, n=1, cutoff=0.6)
    return matches[0] if matches else None

def match_channels(template_channels, all_channels):
    """
    匹配模板中的频道与抓取到的频道。
    :param template_channels: 模板频道信息
    :param all_channels: 所有抓取到的频道信息
    :return: 匹配后的频道信息
    """
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
    """
    过滤源URL，获取匹配后的频道信息。
    :param template_file: 模板文件路径
    :return: 匹配后的频道信息和模板频道信息
    """
    template_channels = parse_template(template_file)
    source_urls = config.source_urls
    all_channels = OrderedDict()
    for url in source_urls:
        fetched_channels = fetch_channels(url)
        merge_channels(all_channels, fetched_channels)
    matched_channels = match_channels(template_channels, all_channels)
    return matched_channels, template_channels

def merge_channels(target, source):
    """
    合并两个频道字典。
    :param target: 目标字典
    :param source: 源字典
    :return: 合并后的字典
    """
    for category, channel_list in source.items():
        if category in target:
            target[category].extend(channel_list)
        else:
            target[category] = channel_list

def is_ipv6(url):
    """
    判断URL是否为IPv6地址。
    :param url: 待判断的URL
    :return: 如果是IPv6地址返回True，否则返回False
    """
    return re.match(r'^http:\/\/<span data-type="block-math" data-value="WzAtOWEtZkEtRjpdKw=="></span>', url) is not None

def test_url_speed(url):
    """
    测试URL的响应时间。
    :param url: 待测试的URL
    :return: 响应时间，如果测试失败返回无穷大
    """
    try:
        start_time = time.time()
        response = requests.head(url, timeout=5)
        response.raise_for_status()
        end_time = time.time()
        return end_time - start_time
    except requests.RequestException:
        return float('inf')

def sort_and_filter_urls(urls, written_urls, limit=20):
    """
    排序和过滤URL，只保留响应时间最短的前limit条URL。
    :param urls: URL列表
    :param written_urls: 已写入的URL集合
    :param limit: 每个频道保留的最大线路数量
    :return: 排序和过滤后的URL列表
    """
    url_speed_pairs = [(url, test_url_speed(url)) for url in urls if url and url not in written_urls and not any(blacklist in url for blacklist in config.url_blacklist)]
    url_speed_pairs.sort(key=lambda x: x[1])
    filtered_urls = [url for url, _ in url_speed_pairs[:limit]]
    written_urls.update(filtered_urls)
    return filtered_urls

def updateChannelUrlsM3U(channels, template_channels):
    """
    更新频道URL到M3U和TXT文件中。
    :param channels: 匹配后的频道信息
    :param template_channels: 模板频道信息
    """
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
        f_m3u_ipv4.write(f"""#EXTM3U x-tvg-url={",".join(f'"{epg_url}"' for epg_url in config.epg_urls)}\n""")
        f_m3u_ipv6.write(f"""#EXTM3U x-tvg-url={",".join(f'"{epg_url}"' for epg_url in config.epg_urls)}\n""")
        for group in config.announcements:
            f_txt_ipv4.write(f"{group['channel']},#genre#\n")
            f_txt_ipv6.write(f"{group['channel']},#genre#\n")
            for announcement in group['entries']:
                url = announcement['url']
                if is_ipv6(url):
                    if url not in written_urls_ipv6:
                        written_urls_ipv6.add(url)
                        f_m3u_ipv6.write(f"""#EXTINF:-1 tvg-id="1" tvg-name="{announcement['name']}" tvg-logo="{announcement['logo']}" group-title="{group['channel']}",{announcement['name']}\n""")
                        f_m3u_ipv6.write(f"{url}\n")
                        f_txt_ipv6.write(f"{announcement['name']},{url}\n")
                else:
                    if url not in written_urls_ipv4:
                        written_urls_ipv4.add(url)
                        f_m3u_ipv4.write(f"""#EXTINF:-1 tvg-id="1" tvg-name="{announcement['name']}" tvg-logo="{announcement['logo']}" group-title="{group['channel']}",{announcement['name']}\n""")
                        f_m3u_ipv4.write(f"{url}\n")
                        f_txt_ipv4.write(f"{announcement['name']},{url}\n")
        for category, channel_list in template_channels.items():
            f_txt_ipv4.write(f"{category},#genre#\n")
            f_txt_ipv6.write(f"{category},#genre#\n")
            if category in channels:
                for channel_name in channel_list:
                    if channel_name in channels[category]:
                        sorted_urls_ipv4 = sort_and_filter_urls(channels[category][channel_name], written_urls_ipv4)
                        sorted_urls_ipv6 = sort_and_filter_urls(channels[category][channel_name], written_urls_ipv6)
                        total_urls_ipv4 = len(sorted_urls_ipv4)
                        total_urls_ipv6 = len(sorted_urls_ipv6)
                        for index, url in enumerate(sorted_urls_ipv4, start=1):
                            new_url = add_url_suffix(url, index, total_urls_ipv4, "IPV4")
                            write_to_files(f_m3u_ipv4, f_txt_ipv4, category, channel_name, index, new_url)
                        for index, url in enumerate(sorted_urls_ipv6, start=1):
                            new_url = add_url_suffix(url, index, total_urls_ipv6, "IPV6")
                            write_to_files(f_m3u_ipv6, f_txt_ipv6, category, channel_name, index, new_url)
        f_txt_ipv4.write("\n")
        f_txt_ipv6.write("\n")

def add_url_suffix(url, index, total_urls, ip_version):
    """
    添加URL后缀。
    :param url: 原始URL
    :param index: 当前URL的索引
    :param total_urls: 总URL数量
    :param ip_version: IP版本
    :return: 添加后缀后的URL
    """
    suffix = f"${ip_version}" if total_urls == 1 else f"${ip_version}•线路{index}"
    base_url = url.split('$', 1)[0] if '$' in url else url
    return f"{base_url}{suffix}"

def write_to_files(f_m3u, f_txt, category, channel_name, index, new_url):
    """
    写入M3U和TXT文件。
    :param f_m3u: M3U文件对象
    :param f_txt: TXT文件对象
    :param category: 频道分类
    :param channel_name: 频道名称
    :param index: 当前URL的索引
    :param new_url: 添加后缀后的URL
    """
    logo_url = f"./pic/logos{channel_name}.png"
    f_m3u.write(f"#EXTINF:-1 tvg-id=\"{index}\" tvg-name=\"{channel_name}\" tvg-logo=\"{logo_url}\" group-title=\"{category}\",{channel_name}\n")
    f_m3u.write(new_url + "\n")
    f_txt.write(f"{channel_name},{new_url}\n")

if __name__ == "__main__":
    template_file = "demo.txt"
    channels, template_channels = filter_source_urls(template_file)
    updateChannelUrlsM3U(channels, template_channels)
