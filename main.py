import re
import requests
import logging
from collections import OrderedDict, defaultdict
from datetime import datetime
import config
import os
import difflib
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

# 确保 output 文件夹存在
output_folder = "output"
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

# 日志记录，将日志文件保存到 output 文件夹下
log_file_path = os.path.join(output_folder, "function.log")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler(log_file_path, "w", encoding="utf-8"), logging.StreamHandler()])

# 测速超时时间（秒）
TEST_TIMEOUT = config.TEST_TIMEOUT

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
    """清洗频道名称，去除特殊字符并统一格式"""
    cleaned_name = re.sub(r'[$「」-]', '', channel_name)
    cleaned_name = re.sub(r'\s+', '', cleaned_name)
    cleaned_name = re.sub(r'(\D*)(\d+)', lambda m: m.group(1) + str(int(m.group(2))), cleaned_name)
    return cleaned_name.upper()

def fetch_channels(url):
    """从指定URL抓取频道列表"""
    channels = OrderedDict()

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        response.encoding = 'utf-8'
        lines = response.text.split("\n")
        is_m3u = any(line.startswith("#EXTINF") for line in lines[:15])
        source_type = "m3u" if is_m3u else "txt"
        logging.info(f"URL: {url} 成功，判断为{source_type}格式")

        if is_m3u:
            channels.update(parse_m3u_lines(lines))
        else:
            channels.update(parse_txt_lines(lines))

        if channels:
            categories = ", ".join(channels.keys())
            logging.info(f"URL: {url} 成功，包含频道分类: {categories}")
    except requests.RequestException as e:
        logging.error(f"URL: {url} 失败❌, Error: {e}")

    return channels

def parse_m3u_lines(lines):
    """解析M3U格式的频道列表行"""
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
    """解析TXT格式的频道列表行"""
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
    """查找最相似的名称"""
    matches = difflib.get_close_matches(target_name, name_list, n=1, cutoff=0.6)
    return matches[0] if matches else None

def match_channels(template_channels, all_channels):
    """匹配模板中的频道与抓取到的频道"""
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
    """过滤源URL，获取匹配后的频道信息"""
    template_channels = parse_template(template_file)
    source_urls = config.source_urls

    all_channels = OrderedDict()
    for url in source_urls:
        fetched_channels = fetch_channels(url)
        merge_channels(all_channels, fetched_channels)

    matched_channels = match_channels(template_channels, all_channels)

    return matched_channels, template_channels

def merge_channels(target, source):
    """合并两个频道字典"""
    for category, channel_list in source.items():
        if category in target:
            target[category].extend(channel_list)
        else:
            target[category] = channel_list

def is_ipv6(url):
    """判断URL是否为IPv6地址"""
    return re.match(r'^http:\/\/\[[0-9a-fA-F:]+\]', url) is not None

def test_stream_speed(url):
    """测试直播源速度"""
    try:
        start_time = time.time()
        response = requests.get(url, stream=True, timeout=TEST_TIMEOUT)
        response.raise_for_status()
        
        bytes_received = 0
        test_duration = 2  # 测试2秒
        end_time = start_time + test_duration
        
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                bytes_received += len(chunk)
                if time.time() > end_time:
                    break
        
        elapsed = time.time() - start_time
        speed = bytes_received / elapsed / 1024  # KB/s
        
        return {
            'url': url,
            'speed': speed,
            'status': 'success',
            'elapsed': elapsed,
            'size': bytes_received
        }
    except Exception as e:
        return {
            'url': url,
            'speed': 0,
            'status': 'failed',
            'error': str(e)
        }

def batch_test_stream_speeds(urls):
    """批量测试直播源速度（多线程）"""
    logging.info(f"开始多线程测速，共{len(urls)}个直播源")
    results = []
    
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        future_to_url = {executor.submit(test_stream_speed, url): url for url in urls}
        
        for future in future_to_url:
            try:
                result = future.result()
                results.append(result)
                if result['status'] == 'success':
                    logging.info(f"测速成功: {result['url']} - {result['speed']:.2f} KB/s")
                else:
                    logging.warning(f"测速失败: {result['url']} - {result.get('error', '未知错误')}")
            except Exception as e:
                logging.error(f"测速异常: {future_to_url[future]} - {str(e)}")
    
    # 按速度排序（降序）
    return sorted(results, key=lambda x: x['speed'], reverse=True)

def updateChannelUrlsM3U(channels, template_channels):
    """更新频道URL到M3U和TXT文件中"""
    written_urls_ipv4 = set()
    written_urls_ipv6 = set()
    
    # 收集所有需要测速的URL
    all_urls = []
    for category, channel_dict in channels.items():
        for channel_name, urls in channel_dict.items():
            for url in urls:
                all_urls.append(url)
    
    # 去重后进行测速
    unique_urls = list(set(all_urls))
    speed_results = batch_test_stream_speeds(unique_urls)
    
    # 构建URL到速度的映射
    url_speed_map = {result['url']: result['speed'] for result in speed_results}
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    for group in config.announcements:
        for announcement in group['entries']:
            if announcement['name'] is None:
                announcement['name'] = current_date

    ipv4_m3u_path = os.path.join(output_folder, "live_ipv4.m3u")
    ipv4_txt_path = os.path.join(output_folder, "live_ipv4.txt")
    ipv6_m3u_path = os.path.join(output_folder, "live_ipv6.m3u")
    ipv6_txt_path = os.path.join(output_folder, "live_ipv6.txt")
    
    # 写入测速结果
    speed_result_path = os.path.join(output_folder, "stream_speeds.txt")
    with open(speed_result_path, "w", encoding="utf-8") as f_speed:
        f_speed.write("直播源测速结果（按速度降序排列）:\n")
        f_speed.write("=" * 80 + "\n")
        for result in speed_results:
            if result['status'] == 'success':
                f_speed.write(f"{result['speed']:>8.2f} KB/s | {result['url']}\n")
            else:
                f_speed.write(f"{'FAILED':>8} | {result['url']} ({result.get('error', '未知错误')})\n")

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
                        speed = url_speed_map.get(url, 0)
                        speed_info = f" ({speed:.2f} KB/s)" if speed > 0 else ""
                        f_m3u_ipv6.write(f"""#EXTINF:-1 tvg-id="1" tvg-name="{announcement['name']}{speed_info}" tvg-logo="{announcement['logo']}" group-title="{group['channel']}",{announcement['name']}{speed_info}\n""")
                        f_m3u_ipv6.write(f"{url}\n")
                        f_txt_ipv6.write(f"{announcement['name']},{url}\n")
                else:
                    if url not in written_urls_ipv4:
                        written_urls_ipv4.add(url)
                        speed = url_speed_map.get(url, 0)
                        speed_info = f" ({speed:.2f} KB/s)" if speed > 0 else ""
                        f_m3u_ipv4.write(f"""#EXTINF:-1 tvg-id="1" tvg-name="{announcement['name']}{speed_info}" tvg-logo="{announcement['logo']}" group-title="{group['channel']}",{announcement['name']}{speed_info}\n""")
                        f_m3u_ipv4.write(f"{url}\n")
                        f_txt_ipv4.write(f"{announcement['name']},{url}\n")

        for category, channel_list in template_channels.items():
            f_txt_ipv4.write(f"{category},#genre#\n")
            f_txt_ipv6.write(f"{category},#genre#\n")
            if category in channels:
                for channel_name in channel_list:
                    if channel_name in channels[category]:
                        # 根据速度排序URL
                        urls_with_speed = [
                            (url, url_speed_map.get(url, 0))
                            for url in channels[category][channel_name]
                        ]
                        urls_with_speed.sort(key=lambda x: x[1], reverse=True)
                        
                        sorted_urls_ipv4 = []
                        sorted_urls_ipv6 = []
                        
                        for url, speed in urls_with_speed:
                            if is_ipv6(url):
                                if url not in written_urls_ipv6:
                                    sorted_urls_ipv6.append((url, speed))
                                    written_urls_ipv6.add(url)
                            else:
                                if url not in written_urls_ipv4:
                                    sorted_urls_ipv4.append((url, speed))
                                    written_urls_ipv4.add(url)

                        total_urls_ipv4 = len(sorted_urls_ipv4)
                        total_urls_ipv6 = len(sorted_urls_ipv6)

                        for index, (url, speed) in enumerate(sorted_urls_ipv4, start=1):
                            new_url = add_url_suffix(url, index, total_urls_ipv4, "IPV4", speed)
                            write_to_files(f_m3u_ipv4, f_txt_ipv4, category, channel_name, index, new_url, speed)

                        for index, (url, speed) in enumerate(sorted_urls_ipv6, start=1):
                            new_url = add_url_suffix(url, index, total_urls_ipv6, "IPV6", speed)
                            write_to_files(f_m3u_ipv6, f_txt_ipv6, category, channel_name, index, new_url, speed)

        f_txt_ipv4.write("\n")
        f_txt_ipv6.write("\n")

def add_url_suffix(url, index, total_urls, ip_version, speed):
    """添加URL后缀，包含速度信息"""
    speed_info = f"({speed:.2f}KB/s)"
    suffix = f"${ip_version}${speed_info}" if total_urls == 1 else f"${ip_version}•线路{index}${speed_info}"
    base_url = url.split('$', 1)[0] if '$' in url else url
    return f"{base_url}{suffix}"

def write_to_files(f_m3u, f_txt, category, channel_name, index, new_url, speed):
    """写入M3U和TXT文件，包含速度信息"""
    logo_url = f"https://gitee.com/IIII-9306/PAV/raw/master/logos/{channel_name}.png"
    speed_info = f" ({speed:.2f} KB/s)"
    f_m3u.write(f"#EXTINF:-1 tvg-id=\"{index}\" tvg-name=\"{channel_name}{speed_info}\" tvg-logo=\"{logo_url}\" group-title=\"{category}\",{channel_name}{speed_info}\n")
    f_m3u.write(new_url + "\n")
    f_txt.write(f"{channel_name},{new_url}\n")

if __name__ == "__main__":
    template_file = "demo.txt"
    logging.info("开始处理直播源...")
    
    # 过滤并匹配频道
    channels, template_channels = filter_source_urls(template_file)
    
    # 更新并写入文件
    updateChannelUrlsM3U(channels, template_channels)
    
    logging.info("处理完成，所有文件已保存到output文件夹")
