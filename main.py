import re
import requests
import logging
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
import config
import os
import difflib
import time
from concurrent.futures import ThreadPoolExecutor
import argparse

# 确保 output 文件夹存在
output_folder = "output"
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

# 日志记录，将日志文件保存到 output 文件夹下
log_file_path = os.path.join(output_folder, "function.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, "w", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# 全局缓存：{url: (speed, timestamp, reliability, size)}
url_metrics_cache = {}
CACHE_TIMEOUT = timedelta(minutes=5)  # 缓存有效期5分钟

# 网络质量监控
network_quality = {"avg_speed": 2.0, "success_rate": 0.9, "last_update": datetime.now()}
quality_history = []
MAX_HISTORY = 20  # 保留最近20次网络质量数据

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
    """清洗频道名称，去除特定字符并转换为大写"""
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

def update_network_quality(speed, success):
    """更新网络质量统计"""
    global network_quality, quality_history
    
    now = datetime.now()
    
    # 清除过期的历史数据
    quality_history = [(s, succ, t) for s, succ, t in quality_history if now - t < CACHE_TIMEOUT]
    
    quality_history.append((speed, success, now))
    if len(quality_history) > MAX_HISTORY:
        quality_history.pop(0)
    
    valid_speeds = [s for s, _, _ in quality_history if s != float('inf')]
    avg_speed = sum(valid_speeds) / len(valid_speeds) if valid_speeds else float('inf')
    success_rate = sum(succ for _, succ, _ in quality_history) / len(quality_history) if quality_history else 0
    
    network_quality = {"avg_speed": avg_speed, "success_rate": success_rate, "last_update": now}
    logging.debug(f"网络质量更新: 平均速度={avg_speed:.2f}s, 成功率={success_rate:.2%}")

def get_adaptive_test_params():
    """根据网络状况获取自适应测试参数"""
    # 如果没有足够的历史数据，使用默认参数
    if not quality_history or datetime.now() - network_quality["last_update"] > timedelta(minutes=10):
        return {"retries": 3, "timeout": 5, "bytes_to_read": 1024}
    
    avg_speed = network_quality["avg_speed"]
    success_rate = network_quality["success_rate"]
    
    # 基本参数
    base_retries = 3
    base_timeout = 5
    base_bytes = 1024
    
    # 根据网络质量调整参数
    retries = max(2, int(base_retries / max(0.1, success_rate)))  # 网络差时增加重试次数
    timeout = min(15, int(base_timeout * (2.0 / max(0.5, avg_speed))))  # 网络差时延长超时时间
    
    # 对于大文件，减少读取的数据量以加快测试速度
    bytes_to_read = base_bytes if avg_speed < 3 else base_bytes // 2
    
    return {"retries": retries, "timeout": timeout, "bytes_to_read": bytes_to_read}

def test_url_speed(url):
    """测试URL的响应速度，使用GET请求并实现自适应参数调整"""
    now = datetime.now()
    
    # 检查缓存
    if url in url_metrics_cache:
        speed, timestamp, reliability, size = url_metrics_cache[url]
        if now - timestamp < CACHE_TIMEOUT:
            logging.debug(f"使用缓存结果: {url} 速度={speed:.2f}s, 可靠性={reliability:.2%}, 大小={size}B")
            return speed, reliability, size
    
    # 获取自适应测试参数
    params = get_adaptive_test_params()
    retries = params["retries"]
    timeout = params["timeout"]
    bytes_to_read = params["bytes_to_read"]
    
    # 实际测试
    times = []
    successes = 0
    content_size = 0
    
    for attempt in range(retries):
        try:
            start_time = time.time()
            # 使用GET请求但限制读取数据量，更准确反映实际加载速度
            with requests.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                
                # 获取内容大小
                content_size = int(response.headers.get('Content-Length', 0))
                
                # 添加读取超时处理
                try:
                    data = response.raw.read(bytes_to_read, decode_content=True)
                    if not data:
                        raise requests.exceptions.ReadTimeout("Empty response")
                except requests.exceptions.ReadTimeout:
                    logging.warning(f"URL读取超时: {url}, 尝试 {attempt+1}/{retries}")
                    continue
                    
            end_time = time.time()
            
            elapsed = end_time - start_time
            times.append(elapsed)
            successes += 1
            
            logging.debug(f"URL测试成功: {url}, 尝试 {attempt+1}/{retries}, 时间={elapsed:.2f}s, 大小={content_size}B")
        except (requests.RequestException, TimeoutError) as e:
            logging.debug(f"URL测试失败: {url}, 尝试 {attempt+1}/{retries}, 错误: {e}")
            continue
    
    # 计算结果
    success_rate = successes / retries if retries > 0 else 0
    avg_speed = sum(times) / len(times) if times else float('inf')
    
    # 更新网络质量统计
    update_network_quality(avg_speed, success_rate)
    
    # 保存到缓存
    url_metrics_cache[url] = (avg_speed, now, success_rate, content_size)
    
    return avg_speed, success_rate, content_size

def sort_and_filter_urls(urls, written_urls, limit=20, max_workers=10):
    """使用线程池并行测试URL速度，并根据响应时间和可靠性排序过滤"""
    valid_urls = [
        url for url in urls 
        if url and 
        url not in written_urls and 
        not any(blacklist in url for blacklist in config.url_blacklist)
    ]
    
    if not valid_urls:
        return []
    
    logging.info(f"开始并行测试 {len(valid_urls)} 个URL，使用 {max_workers} 个工作线程")
    
    # 使用线程池并行测试
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        url_metrics = list(executor.map(
            lambda url: (url, *test_url_speed(url)), 
            valid_urls
        ))
    
    # 根据速度和可靠性综合排序
    # 评分为: 速度(权重70%) + 可靠性(权重30%)
    url_metrics.sort(key=lambda x: x[1] * 0.7 + (1 - x[2]) * 0.3 * 10)
    
    # 只保留前limit条
    filtered_urls = [url for url, _, _, _ in url_metrics[:limit]]
    written_urls.update(filtered_urls)
    
    logging.info(f"URL排序完成: 原始数量={len(urls)}, 有效数量={len(valid_urls)}, 保留数量={len(filtered_urls)}")
    return filtered_urls

def updateChannelUrlsM3U(channels, template_channels, max_workers=10, limit=20):
    """更新频道URL到M3U和TXT文件中"""
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
    
    logging.info(f"开始生成M3U和TXT文件，每个频道保留最多 {limit} 条线路")
    
    with open(ipv4_m3u_path, "w", encoding="utf-8") as f_m3u_ipv4, \
         open(ipv4_txt_path, "w", encoding="utf-8") as f_txt_ipv4, \
         open(ipv6_m3u_path, "w", encoding="utf-8") as f_m3u_ipv6, \
         open(ipv6_txt_path, "w", encoding="utf-8") as f_txt_ipv6:
        
        # 写入M3U文件头部
        epg_urls_str = ",".join([f'"{url}"' for url in config.epg_urls])
        f_m3u_ipv4.write(f'#EXTM3U x-tvg-url={epg_urls_str}\n')
        f_m3u_ipv6.write(f'#EXTM3U x-tvg-url={epg_urls_str}\n')
        
        # 写入公告频道
        for group in config.announcements:
            f_txt_ipv4.write(f"{group['channel']},#genre#\n")
            f_txt_ipv6.write(f"{group['channel']},#genre#\n")
            
            for announcement in group['entries']:
                url = announcement['url']
                if is_ipv6(url):
                    if url not in written_urls_ipv6:
                        written_urls_ipv6.add(url)
                        f_m3u_ipv6.write(
                            f"#EXTINF:-1 tvg-id=\"1\" tvg-name=\"{announcement['name']}\" "
                            f"tvg-logo=\"{announcement['logo']}\" group-title=\"{group['channel']}\","
                            f"{announcement['name']}\n"
                        )
                        f_m3u_ipv6.write(f"{url}\n")
                        f_txt_ipv6.write(f"{announcement['name']},{url}\n")
                else:
                    if url not in written_urls_ipv4:
                        written_urls_ipv4.add(url)
                        f_m3u_ipv4.write(
                            f"#EXTINF:-1 tvg-id=\"1\" tvg-name=\"{announcement['name']}\" "
                            f"tvg-logo=\"{announcement['logo']}\" group-title=\"{group['channel']}\","
                            f"{announcement['name']}\n"
                        )
                        f_m3u_ipv4.write(f"{url}\n")
                        f_txt_ipv4.write(f"{announcement['name']},{url}\n")
        
        # 写入常规频道
        total_channels = sum(len(channels.get(cat, {})) for cat in template_channels)
        processed_channels = 0
        
        for category, channel_list in template_channels.items():
            f_txt_ipv4.write(f"{category},#genre#\n")
            f_txt_ipv6.write(f"{category},#genre#\n")
            
            if category in channels:
                for channel_name in channel_list:
                    if channel_name in channels[category]:
                        processed_channels += 1
                        logging.info(f"处理频道: {category} - {channel_name} ({processed_channels}/{total_channels})")
                        
                        # 分别处理IPv4和IPv6地址
                        sorted_urls_ipv4 = sort_and_filter_urls(
                            channels[category][channel_name], 
                            written_urls_ipv4,
                            limit=limit,
                            max_workers=max_workers
                        )
                        sorted_urls_ipv6 = sort_and_filter_urls(
                            channels[category][channel_name], 
                            written_urls_ipv6,
                            limit=limit,
                            max_workers=max_workers
                        )
                        
                        # 写入IPv4线路
                        total_ipv4 = len(sorted_urls_ipv4)
                        for index, url in enumerate(sorted_urls_ipv4, start=1):
                            new_url = add_url_suffix(url, index, total_ipv4, "IPV4")
                            write_to_files(f_m3u_ipv4, f_txt_ipv4, category, channel_name, index, new_url)
                        
                        # 写入IPv6线路
                        total_ipv6 = len(sorted_urls_ipv6)
                        for index, url in enumerate(sorted_urls_ipv6, start=1):
                            new_url = add_url_suffix(url, index, total_ipv6, "IPV6")
                            write_to_files(f_m3u_ipv6, f_txt_ipv6, category, channel_name, index, new_url)
        
        f_txt_ipv4.write("\n")
        f_txt_ipv6.write("\n")
    
    logging.info(f"M3U和TXT文件生成完成，共处理 {processed_channels} 个频道")

def add_url_suffix(url, index, total_urls, ip_version):
    """添加URL后缀"""
    suffix = f"${ip_version}" if total_urls == 1 else f"${ip_version}•线路{index}"
    base_url = url.split('$', 1)[0] if '$' in url else url
    return f"{base_url}{suffix}"

def write_to_files(f_m3u, f_txt, category, channel_name, index, new_url):
    """写入M3U和TXT文件"""
    logo_url = f"./pic/logos{channel_name}.png"
    f_m3u.write(
        f"#EXTINF:-1 tvg-id=\"{index}\" tvg-name=\"{channel_name}\" "
        f"tvg-logo=\"{logo_url}\" group-title=\"{category}\","
        f"{channel_name}\n"
    )
    f_m3u.write(f"{new_url}\n")
    f_txt.write(f"{channel_name},{new_url}\n")

def main():
    parser = argparse.ArgumentParser(description='IPTV频道列表生成工具')
    parser.add_argument('--template', type=str, help='模板文件路径')
    parser.add_argument('--workers', type=int, help='并行测试的工作线程数')
    parser.add_argument('--limit', type=int, help='每个频道保留的最大线路数量')
    parser.add_argument('--verbose', action='store_true', help='启用详细日志')
    parser.add_argument('--config', type=str, help='配置文件路径')
    args = parser.parse_args()
    
    # 创建一个局部变量保存配置
    local_config = config
    
    # 加载配置文件（如果提供）
    if args.config:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("custom_config", args.config)
            custom_config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(custom_config)
            local_config = custom_config  # 使用自定义配置
        except Exception as e:
            logging.error(f"加载配置文件失败: {e}")
            return
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 获取各参数值，优先使用命令行参数，其次使用配置文件，最后使用默认值
    template_file = get_config_value(args, local_config, 'template_file', 'demo.txt')
    max_workers = get_config_value(args, local_config, 'max_workers', 10)  # 移除psutil依赖，使用固定值
    limit = get_config_value(args, local_config, 'limit', 20)
    
    logging.info(f"开始生成IPTV播放列表，参数: 工作线程={max_workers}, 每个频道保留线路={limit}")
    
    channels, template_channels = filter_source_urls(template_file)
    
    total_urls = sum(len(urls) for cat in channels.values() for urls in cat.values())
    logging.info(f"共找到 {total_urls} 个候选URL，开始测速...")
    
    updateChannelUrlsM3U(channels, template_channels, max_workers=max_workers, limit=limit)
    
    logging.info("IPTV播放列表生成完成!")
    logging.info(f"IPv4 M3U文件: {os.path.abspath(os.path.join(output_folder, 'live_ipv4.m3u'))}")
    logging.info(f"IPv4 TXT文件: {os.path.abspath(os.path.join(output_folder, 'live_ipv4.txt'))}")
    logging.info(f"IPv6 M3U文件: {os.path.abspath(os.path.join(output_folder, 'live_ipv6.m3u'))}")
    logging.info(f"IPv6 TXT文件: {os.path.abspath(os.path.join(output_folder, 'live_ipv6.txt'))}")

def get_config_value(args, config_obj, attr_name, default=None):
    """从命令行参数或配置文件获取值"""
    if hasattr(args, attr_name) and getattr(args, attr_name) is not None:
        return getattr(args, attr_name)
    elif hasattr(config_obj, attr_name):
        return getattr(config_obj, attr_name)
    else:
        return default

if __name__ == "__main__":
    main()    
