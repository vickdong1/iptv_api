import re
import requests
import logging
from collections import OrderedDict
from datetime import datetime
import config
import os
import difflib
import asyncio
import aiohttp
import subprocess

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("function.log", "w", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# 确保输出目录存在
output_folder = "output"
os.makedirs(output_folder, exist_ok=True)

def parse_template(template_file: str) -> OrderedDict:
    """解析模板文件，提取频道分类和名称"""
    template_channels = OrderedDict()
    current_category = None

    try:
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
        logging.info(f"成功解析模板文件: {template_file}")
        return template_channels
    except Exception as e:
        logging.error(f"解析模板文件失败: {e}")
        raise

def clean_channel_name(channel_name: str) -> str:
    """清洗频道名称，统一格式"""
    cleaned = re.sub(r'[$「」-]', '', channel_name)
    cleaned = re.sub(r'\s+', '', cleaned)
    cleaned = re.sub(r'(\D*)(\d+)', lambda m: m.group(1) + str(int(m.group(2))), cleaned)
    return cleaned.upper()

async def fetch_channels(url: str) -> OrderedDict:
    """异步从URL抓取频道列表"""
    channels = OrderedDict()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                content = await response.text(encoding='utf-8')
        
        lines = content.split("\n")
        is_m3u = any(line.startswith("#EXTINF") for line in lines[:15])
        source_type = "m3u" if is_m3u else "txt"
        logging.info(f"URL: {url} 解析为{source_type}格式")

        if is_m3u:
            channels.update(parse_m3u_lines(lines))
        else:
            channels.update(parse_txt_lines(lines))

        if channels:
            categories = ", ".join(channels.keys())
            logging.info(f"URL: {url} 包含分类: {categories}")
        
        return channels
    except Exception as e:
        logging.error(f"抓取URL失败: {url}, 错误: {e}")
        return OrderedDict()

def parse_m3u_lines(lines: list) -> OrderedDict:
    """解析M3U格式的频道列表"""
    channels = OrderedDict()
    current_category = None
    current_name = None

    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF"):
            match = re.search(r'group-title="(.*?)",(.*)', line)
            if match:
                current_category = match.group(1).strip()
                current_name = match.group(2).strip()
                if current_name and current_name.startswith("CCTV"):
                    current_name = clean_channel_name(current_name)
                if current_category not in channels:
                    channels[current_category] = []
        elif line and not line.startswith("#") and current_category and current_name:
            channel_url = line.strip()
            channels[current_category].append((current_name, channel_url))
    
    return channels

def parse_txt_lines(lines: list) -> OrderedDict:
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
                if channel_name and channel_name.startswith("CCTV"):
                    channel_name = clean_channel_name(channel_name)
                channel_urls = match.group(2).strip().split('#')
                for url in channel_urls:
                    url = url.strip()
                    if url:
                        channels[current_category].append((channel_name, url))
            elif line:
                channels[current_category].append((line, ''))
    
    return channels

def find_similar_name(target_name: str, name_list: list) -> str:
    """查找最相似的频道名称"""
    matches = difflib.get_close_matches(target_name, name_list, n=1, cutoff=0.6)
    return matches[0] if matches else None

async def filter_source_urls(template_file: str) -> tuple:
    """过滤源URL，获取匹配后的频道信息"""
    template_channels = parse_template(template_file)
    source_urls = config.source_urls

    all_channels = OrderedDict()
    tasks = [fetch_channels(url) for url in source_urls]
    results = await asyncio.gather(*tasks)

    for result in results:
        for category, channels in result.items():
            if category in all_channels:
                all_channels[category].extend(channels)
            else:
                all_channels[category] = channels

    matched_channels = match_channels(template_channels, all_channels)
    return matched_channels, template_channels

def match_channels(template_channels: OrderedDict, all_channels: OrderedDict) -> OrderedDict:
    """匹配模板频道与在线频道"""
    matched_channels = OrderedDict()
    all_online_names = [name for category in all_channels.values() for name, _ in category]

    for category, channel_list in template_channels.items():
        matched_channels[category] = OrderedDict()
        for channel_name in channel_list:
            similar_name = find_similar_name(channel_name, all_online_names)
            if similar_name:
                for online_category, online_channels in all_channels.items():
                    for online_name, online_url in online_channels:
                        if online_name == similar_name:
                            matched_channels[category].setdefault(channel_name, []).append(online_url)
    
    return matched_channels

def is_ipv6(url: str) -> bool:
    """判断URL是否为IPv6地址"""
    return re.match(r'^http:\/\/\[[0-9a-fA-F:]+\]', url) is not None

def update_channel_urls_m3u(channels: OrderedDict, template_channels: OrderedDict) -> None:
    """更新频道URL到M3U和TXT文件"""
    written_urls_ipv4 = set()
    written_urls_ipv6 = set()
    current_date = datetime.now().strftime("%Y-%m-%d")

    # 准备输出文件路径
    ipv4_m3u_path = os.path.join(output_folder, "live_ipv4.m3u")
    ipv4_txt_path = os.path.join(output_folder, "live_ipv4.txt")
    ipv6_m3u_path = os.path.join(output_folder, "live_ipv6.m3u")
    ipv6_txt_path = os.path.join(output_folder, "live_ipv6.txt")

    with open(ipv4_m3u_path, "w", encoding="utf-8") as f_m3u_ipv4, \
         open(ipv4_txt_path, "w", encoding="utf-8") as f_txt_ipv4, \
         open(ipv6_m3u_path, "w", encoding="utf-8") as f_m3u_ipv6, \
         open(ipv6_txt_path, "w", encoding="utf-8") as f_txt_ipv6:

        # 写入M3U头部信息
        f_m3u_ipv4.write(f"#EXTM3U x-tvg-url={','.join(f'"{epg_url}"' for epg_url in config.epg_urls)}\n")
        f_m3u_ipv6.write(f"#EXTM3U x-tvg-url={','.join(f'"{epg_url}"' for epg_url in config.epg_urls)}\n")

        # 写入公告频道
        for group in config.announcements:
            f_txt_ipv4.write(f"{group['channel']},#genre#\n")
            f_txt_ipv6.write(f"{group['channel']},#genre#\n")
            for announcement in group['entries']:
                url = announcement['url']
                name = announcement['name'] or current_date
                if is_ipv6(url):
                    if url not in written_urls_ipv6:
                        written_urls_ipv6.add(url)
                        f_m3u_ipv6.write(f"#EXTINF:-1 tvg-id=\"1\" tvg-name=\"{name}\" tvg-logo=\"{announcement['logo']}\" group-title=\"{group['channel']}\",{name}\n")
                        f_m3u_ipv6.write(f"{url}\n")
                        f_txt_ipv6.write(f"{name},{url}\n")
                else:
                    if url not in written_urls_ipv4:
                        written_urls_ipv4.add(url)
                        f_m3u_ipv4.write(f"#EXTINF:-1 tvg-id=\"1\" tvg-name=\"{name}\" tvg-logo=\"{announcement['logo']}\" group-title=\"{group['channel']}\",{name}\n")
                        f_m3u_ipv4.write(f"{url}\n")
                        f_txt_ipv4.write(f"{name},{url}\n")

        # 写入匹配的频道
        for category, channel_list in template_channels.items():
            f_txt_ipv4.write(f"{category},#genre#\n")
            f_txt_ipv6.write(f"{category},#genre#\n")
            if category in channels:
                for channel_name, urls in channels[category].items():
                    for url in urls:
                        if is_ipv6(url):
                            if url not in written_urls_ipv6:
                                written_urls_ipv6.add(url)
                                f_m3u_ipv6.write(f"#EXTINF:-1 tvg-id=\"1\" tvg-name=\"{channel_name}\" tvg-logo=\"\" group-title=\"{category}\",{channel_name}\n")
                                f_m3u_ipv6.write(f"{url}\n")
                                f_txt_ipv6.write(f"{channel_name},{url}\n")
                        else:
                            if url not in written_urls_ipv4:
                                written_urls_ipv4.add(url)
                                f_m3u_ipv4.write(f"#EXTINF:-1 tvg-id=\"1\" tvg-name=\"{channel_name}\" tvg-logo=\"\" group-title=\"{category}\",{channel_name}\n")
                                f_m3u_ipv4.write(f"{url}\n")
                                f_txt_ipv4.write(f"{channel_name},{url}\n")

async def test_url_aiohttp(url: str) -> float:
    """使用aiohttp测试URL响应时间"""
    try:
        async with aiohttp.ClientSession() as session:
            start_time = asyncio.get_event_loop().time()
            async with session.get(url, timeout=10) as response:
                await response.read()
                return asyncio.get_event_loop().time() - start_time
    except Exception as e:
        logging.error(f"URL: {url}, aiohttp测试失败: {e}")
        return None

def test_url_ffmpeg(url: str) -> float:
    """使用FFmpeg测试URL响应时间"""
    try:
        command = f'ffmpeg -i "{url}" -v error -t 1 -f null - 2>&1 | grep -oP "(?<=time=)[^ ]+"'
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout:
            return float(result.stdout.strip())
        else:
            logging.error(f"URL: {url}, FFmpeg测试失败: {result.stderr.strip()}")
            return None
    except Exception as e:
        logging.error(f"URL: {url}, FFmpeg测试失败: {e}")
        return None

async def test_all_urls(channels: OrderedDict) -> None:
    """测试所有频道URL的响应时间"""
    all_urls = []
    for category in channels.values():
        for urls in category.values():
            all_urls.extend(urls)

    # 去重URL
    unique_urls = list(set(all_urls))
    logging.info(f"准备测试{len(unique_urls)}个唯一URL")

    # 并发测试所有URL
    aiohttp_tasks = [test_url_aiohttp(url) for url in unique_urls]
    aiohttp_results = await asyncio.gather(*aiohttp_tasks)

    # 记录测试结果
    test_results = []
    for url, aiohttp_time in zip(unique_urls, aiohttp_results):
        ffmpeg_time = test_url_ffmpeg(url)
        test_results.append({
            'url': url,
            'aiohttp_time': aiohttp_time,
            'ffmpeg_time': ffmpeg_time
        })
        logging.info(f"URL: {url}, aiohttp响应时间: {aiohttp_time:.2f}s, FFmpeg响应时间: {ffmpeg_time:.2f}s")

    # 保存测试结果
    with open(os.path.join(output_folder, "speed_test_results.txt"), "w", encoding="utf-8") as f:
        f.write("URL测试结果:\n")
        f.write("=" * 50 + "\n")
        for result in sorted(test_results, key=lambda x: x.get('aiohttp_time') or float('inf')):
            f.write(f"URL: {result['url']}\n")
            f.write(f"aiohttp响应时间: {result['aiohttp_time']:.2f}s\n")
            f.write(f"FFmpeg响应时间: {result['ffmpeg_time']:.2f}s\n")
            f.write("-" * 50 + "\n")

async def main():
    """主函数"""
    try:
        template_file = "demo.txt"
        logging.info("开始处理频道列表...")
        
        # 过滤源URL并获取匹配的频道
        matched_channels, template_channels = await filter_source_urls(template_file)
        
        # 更新M3U和TXT文件
        update_channel_urls_m3u(matched_channels, template_channels)
        logging.info("成功更新频道文件")
        
        # 测试所有URL的响应时间
        await test_all_urls(matched_channels)
        logging.info("完成所有URL的响应时间测试")
        
        logging.info("任务全部完成!")
    except Exception as e:
        logging.error(f"主程序运行失败: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())
