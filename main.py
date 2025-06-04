import re
import requests
import logging
from collections import OrderedDict
from datetime import datetime
import config
import os
import difflib
import time
import m3u8

# 确保 output 文件夹存在
output_folder = "output"
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

# 日志记录
log_file_path = os.path.join(output_folder, "function.log")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler(log_file_path, "w", encoding="utf-8"), logging.StreamHandler()])

# 配置项
MAX_RETRIES = 3
HTTP_TIMEOUT = 5  # HTTP请求超时时间（秒）
M3U8_TIMEOUT = 10  # M3U8解析超时时间（秒）
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}  # 模拟浏览器请求头

# 缓存有效链接
valid_url_cache = {}
# 缓存无效链接（避免重复验证）
invalid_url_cache = {}

def parse_template(template_file):
    """解析模板文件，提取频道分类和名称"""
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
    """清洗频道名称，提高匹配准确率"""
    cleaned_name = re.sub(r'[$「」-]', '', channel_name)  # 移除特殊字符
    cleaned_name = re.sub(r'\s+', '', cleaned_name)  # 移除空白字符
    cleaned_name = re.sub(r'(\D*)(\d+)', lambda m: m.group(1) + str(int(m.group(2))), cleaned_name)  # 规范化数字
    return cleaned_name.upper()  # 统一转换为大写

def test_url_validity(url):
    """混合验证URL有效性：先HTTP检查，再对M3U8进行深度解析"""
    if url in valid_url_cache:
        return True
    if url in invalid_url_cache:
        return False
    
    for attempt in range(MAX_RETRIES):
        try:
            # 1. 快速HTTP检查（HEAD请求）
            response = requests.head(url, headers=headers, timeout=HTTP_TIMEOUT)
            if response.status_code >= 400:
                raise requests.RequestException(f"HTTP status {response.status_code}")
            
            # 2. 对M3U8文件进行深度解析
            if url.endswith(('.m3u8', '.m3u')):
                m3u8_obj = m3u8.load(url, headers=headers, timeout=M3U8_TIMEOUT)
                if not m3u8_obj.segments and not m3u8_obj.playlists:
                    raise ValueError("Empty M3U8 file")
                
                # 验证主播放列表中的子流
                if m3u8_obj.is_variant:
                    valid_substreams = 0
                    for playlist in m3u8_obj.playlists[:3]:  # 仅检查前3个子流
                        try:
                            sub_url = playlist.uri
                            if not sub_url.startswith('http'):
                                base_url = url.rsplit('/', 1)[0]
                                sub_url = f"{base_url}/{sub_url}"
                            sub_m3u8 = m3u8.load(sub_url, headers=headers, timeout=M3U8_TIMEOUT)
                            if sub_m3u8.segments:
                                valid_substreams += 1
                        except Exception:
                            continue
                    if valid_substreams == 0:
                        raise ValueError("No valid substreams found")
                
                logging.info(f"URL验证成功: {url}")
                valid_url_cache[url] = True
                return True
            
            # 非M3U8文件，仅通过HTTP检查即可
            logging.info(f"URL验证成功: {url}")
            valid_url_cache[url] = True
            return True
            
        except (requests.RequestException, m3u8.HTTPError, m3u8.ParsingError, ValueError) as e:
            logging.warning(f"URL验证失败 (尝试 {attempt+1}/{MAX_RETRIES}): {url} - {str(e)}")
            if attempt == MAX_RETRIES - 1:
                invalid_url_cache[url] = True
                return False
    
    invalid_url_cache[url] = True
    return False

def get_best_url(urls):
    """根据响应速度和质量选择最佳URL"""
    valid_urls = []
    
    # 并行验证URL（简化版，实际可使用线程池）
    for url in urls:
        if test_url_validity(url):
            valid_urls.append(url)
    
    if not valid_urls:
        return None
    
    # 对有效URL进行测速
    results = []
    for url in valid_urls:
        try:
            start_time = time.time()
            response = requests.head(url, headers=headers, timeout=HTTP_TIMEOUT)
            elapsed_time = time.time() - start_time
            results.append((url, elapsed_time, response.headers.get('content-length')))
        except Exception:
            continue
    
    # 排序：优先响应时间，其次内容长度（推测为码率）
    results.sort(key=lambda x: (x[1], -int(x[2] or 0)))
    return results[0][0] if results else None

def fetch_channels(url):
    """从指定URL抓取频道列表"""
    channels = OrderedDict()

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        response.encoding = 'utf-8'
        lines = response.text.split("\n")
        
        # 判断文件类型
        is_m3u = any(line.startswith("#EXTINF") for line in lines[:15])
        is_flv = any(line.endswith('.flv') for line in lines)
        source_type = "m3u" if is_m3u else "flv" if is_flv else "txt"
        logging.info(f"URL: {url} 解析成功，类型: {source_type}")

        # 解析频道
        if is_m3u:
            channels.update(parse_m3u_lines(lines))
        else:
            channels.update(parse_txt_lines(lines))

        if channels:
            categories = ", ".join(channels.keys())
            logging.info(f"URL: {url} 包含分类: {categories}")
            
            # 验证抓取的频道数量
            channel_count = sum(len(ch_list) for ch_list in channels.values())
            if channel_count < 5:
                logging.warning(f"URL: {url} 频道数量过少 ({channel_count})，可能解析失败")
                
        return channels
        
    except requests.RequestException as e:
        logging.error(f"URL: {url} 请求失败 - {str(e)}")
        return OrderedDict()
    except Exception as e:
        logging.error(f"URL: {url} 解析异常 - {str(e)}")
        return OrderedDict()

def parse_m3u_lines(lines):
    """解析M3U格式的频道列表"""
    channels = OrderedDict()
    current_category = None

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
            if current_category and channel_name:
                channel_url = line.strip()
                channels[current_category].append((channel_name, channel_url))

    return channels

def parse_txt_lines(lines):
    """解析TXT格式的频道列表"""
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
                
                # 处理多个URL（用#分隔）
                channel_urls = match.group(2).strip().split('#')
                for url in channel_urls:
                    url = url.strip()
                    if url:
                        channels[current_category].append((channel_name, url))
            elif line:
                channels[current_category].append((line, ''))

    return channels

def find_similar_name(target_name, name_list):
    """查找最相似的频道名称"""
    matches = difflib.get_close_matches(target_name, name_list, n=1, cutoff=0.6)
    return matches[0] if matches else None

def match_channels(template_channels, all_channels):
    """将模板频道与抓取的频道进行匹配"""
    matched_channels = OrderedDict()

    # 构建在线频道名称索引
    all_online_channel_names = []
    for online_category, channel_list in all_channels.items():
        for channel_name, _ in channel_list:
            all_online_channel_names.append(channel_name)

    # 执行匹配
    for category, channel_list in template_channels.items():
        matched_channels[category] = OrderedDict()
        for channel_name in channel_list:
            similar_name = find_similar_name(channel_name, all_online_channel_names)
            if similar_name:
                # 收集所有匹配的URL
                urls = []
                for online_category, online_channel_list in all_channels.items():
                    for online_name, url in online_channel_list:
                        if online_name == similar_name:
                            urls.append(url)
                
                if urls:
                    matched_channels[category][channel_name] = urls
                    logging.info(f"匹配成功: {channel_name} -> {similar_name} ({len(urls)}个源)")
                else:
                    logging.warning(f"匹配失败: {channel_name}")

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
    return re.match(r'^http://\[[0-9a-fA-F:]+\]', url) is not None

def updateChannelUrlsM3U(channels, template_channels):
    """更新频道URL到M3U和TXT文件中"""
    written_urls_ipv4 = set()
    written_urls_ipv6 = set()

    current_date = datetime.now().strftime("%Y-%m-%d")
    # 处理公告频道
    for group in config.announcements:
        for announcement in group['entries']:
            if announcement['name'] is None:
                announcement['name'] = current_date

    # 创建输出文件
    ipv4_m3u_path = os.path.join(output_folder, "live_ipv4.m3u")
    ipv4_txt_path = os.path.join(output_folder, "live_ipv4.txt")
    ipv6_m3u_path = os.path.join(output_folder, "live_ipv6.m3u")
    ipv6_txt_path = os.path.join(output_folder, "live_ipv6.txt")

    with open(ipv4_m3u_path, "w", encoding="utf-8") as f_m3u_ipv4, \
         open(ipv4_txt_path, "w", encoding="utf-8") as f_txt_ipv4, \
         open(ipv6_m3u_path, "w", encoding="utf-8") as f_m3u_ipv6, \
         open(ipv6_txt_path, "w", encoding="utf-8") as f_txt_ipv6:

        # 写入文件头
        f_m3u_ipv4.write(f"#EXTM3U x-tvg-url={','.join(f'"{epg_url}"' for epg_url in config.epg_urls)}\n")
        f_m3u_ipv6.write(f"#EXTM3U x-tvg-url={','.join(f'"{epg_url}"' for epg_url in config.epg_urls)}\n")

        # 写入公告频道
        for group in config.announcements:
            f_txt_ipv4.write(f"{group['channel']},#genre#\n")
            f_txt_ipv6.write(f"{group['channel']},#genre#\n")
            for announcement in group['entries']:
                url = announcement['url']
                if url:
                    if is_ipv6(url):
                        if url not in written_urls_ipv6 and test_url_validity(url):
                            written_urls_ipv6.add(url)
                            f_m3u_ipv6.write(f"#EXTINF:-1 tvg-id=\"1\" tvg-name=\"{announcement['name']}\" tvg-logo=\"{announcement['logo']}\" group-title=\"{group['channel']}\" tvg-language=\"Chinese\" tvg-country=\"CN\",{announcement['name']}\n")
                            f_m3u_ipv6.write(f"{url}\n")
                            f_txt_ipv6.write(f"{announcement['name']},{url}\n")
                    else:
                        if url not in written_urls_ipv4 and test_url_validity(url):
                            written_urls_ipv4.add(url)
                            f_m3u_ipv4.write(f"#EXTINF:-1 tvg-id=\"1\" tvg-name=\"{announcement['name']}\" tvg-logo=\"{announcement['logo']}\" group-title=\"{group['channel']}\" tvg-language=\"Chinese\" tvg-country=\"CN\",{announcement['name']}\n")
                            f_m3u_ipv4.write(f"{url}\n")
                            f_txt_ipv4.write(f"{announcement['name']},{url}\n")

        # 写入匹配的频道
        for category, channel_list in template_channels.items():
            f_txt_ipv4.write(f"{category},#genre#\n")
            f_txt_ipv6.write(f"{category},#genre#\n")
            if category in channels:
                for channel_name in channel_list:
                    if channel_name in channels[category]:
                        urls = channels[category][channel_name]
                        if not urls:
                            continue
                            
                        # 分离IPv4和IPv6地址
                        ipv4_urls = [url for url in urls if not is_ipv6(url)]
                        ipv6_urls = [url for url in urls if is_ipv6(url)]

                        # 为每个IP版本选择最佳URL
                        best_ipv4_url = get_best_url(ipv4_urls)
                        best_ipv6_url = get_best_url(ipv6_urls)

                        # 写入IPv4 URL
                        if best_ipv4_url:
                            new_url = add_url_suffix(best_ipv4_url, 1, 1, "IPV4")
                            write_to_files(f_m3u_ipv4, f_txt_ipv4, category, channel_name, 1, new_url)

                        # 写入IPv6 URL
                        if best_ipv6_url:
                            new_url = add_url_suffix(best_ipv6_url, 1, 1, "IPV6")
                            write_to_files(f_m3u_ipv6, f_txt_ipv6, category, channel_name, 1, new_url)

        # 添加文件结束标记
        f_txt_ipv4.write("\n")
        f_txt_ipv6.write("\n")

def add_url_suffix(url, index, total_urls, ip_version):
    """为URL添加后缀，标识IP版本和线路号"""
    suffix = f"${ip_version}" if total_urls == 1 else f"${ip_version}•线路{index}"
    base_url = url.split('$', 1)[0] if '$' in url else url
    return f"{base_url}{suffix}"

def write_to_files(f_m3u, f_txt, category, channel_name, index, new_url):
    """写入M3U和TXT文件"""
    logo_url = f"./pic/logos{channel_name}.png"
    f_m3u.write(f"#EXTINF:-1 tvg-id=\"{index}\" tvg-name=\"{channel_name}\" tvg-logo=\"{logo_url}\" group-title=\"{category}\" tvg-language=\"Chinese\" tvg-country=\"CN\",{channel_name}\n")
    f_m3u.write(f"{new_url}\n")
    f_txt.write(f"{channel_name},{new_url}\n")

if __name__ == "__main__":
    template_file = "demo.txt"
    logging.info("开始生成频道列表...")
    channels, template_channels = filter_source_urls(template_file)
    updateChannelUrlsM3U(channels, template_channels)
    logging.info(f"频道列表生成完成！共处理 {sum(len(channels.get(cat, {})) for cat in template_channels)} 个频道")
