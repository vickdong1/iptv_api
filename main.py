import re
import requests
import logging
from collections import OrderedDict
from datetime import datetime
import config
import asyncio
from utils.speed_test import batch_speed_test
from utils.parser import parse_template, parse_source_content


# 日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("function.log", "w", encoding="utf-8"), logging.StreamHandler()])


def clean_channel_name(channel_name):
    """
    清洗频道名称，去除特定字符，去除空白字符，将数字部分转换为整数，并转换为大写
    :param channel_name: 原始频道名称
    :return: 清洗后的频道名称
    """
    cleaned_name = re.sub(r'[$「」-]', '', channel_name)  # 去掉中括号、«», 和'-'字符
    cleaned_name = re.sub(r'\s+', '', cleaned_name)  # 去掉所有空白字符
    cleaned_name = re.sub(r'(\D*)(\d+)', lambda m: m.group(1) + str(int(m.group(2))), cleaned_name)  # 将数字前面的部分保留，数字转换为整数
    return cleaned_name.upper()


def fetch_channels(url):
    """
    从指定URL抓取频道列表
    :param url: 直播源URL
    :return: 频道字典
    """
    channels = OrderedDict()
    try:
        response = requests.get(url)
        response.raise_for_status()
        response.encoding = 'utf-8'
        content = response.text
        is_m3u = any(line.startswith("#EXTINF") for line in content.split("\n")[:15])
        source_type = "m3u" if is_m3u else "txt"
        logging.info(f"url: {url} 成功，判断为{source_type}格式")
        channels = parse_source_content(content, source_type)
        if channels:
            categories = ", ".join(channels.keys())
            logging.info(f"url: {url} 成功，包含频道分类: {categories}")
    except requests.RequestException as e:
        logging.error(f"url: {url} 失败❌, Error: {e}")
    return channels


def match_channels(template_channels, all_channels):
    """
    匹配模板中的频道与抓取到的频道
    :param template_channels: 模板频道字典
    :param all_channels: 所有抓取到的频道字典
    :return: 匹配后的频道字典
    """
    matched_channels = OrderedDict()
    for category, channel_list in template_channels.items():
        matched_channels[category] = OrderedDict()
        for channel_name in channel_list:
            for online_category, online_channel_list in all_channels.items():
                for online_channel_name, online_channel_url in online_channel_list:
                    if channel_name == online_channel_name:
                        # 匹配成功的频道信息加入结果中
                        matched_channels[category].setdefault(channel_name, []).append(online_channel_url)
    return matched_channels


def filter_source_urls(template_file):
    """
    过滤源URL，获取匹配后的频道信息
    :param template_file: 模板文件路径
    :return: 匹配后的频道字典和模板频道字典
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
    合并两个频道字典
    :param target: 目标频道字典
    :param source: 源频道字典
    """
    for category, channel_list in source.items():
        if category in target:
            target[category].extend(channel_list)
        else:
            target[category] = channel_list


def is_ipv6(url):
    """
    判断URL是否为IPv6地址
    :param url: 待判断的URL
    :return: 如果是IPv6地址返回True，否则返回False
    """
    return re.match(r'^http:\/\/\[[0-9a-fA-F:]+\]', url) is not None


def updateChannelUrlsM3U(channels, template_channels):
    """
    更新频道URL到M3U和TXT文件中
    :param channels: 匹配后的频道字典
    :param template_channels: 模板频道字典
    """
    written_urls_ipv4 = set()
    written_urls_ipv6 = set()
    current_date = datetime.now().strftime("%Y-%m-%d")
    for group in config.announcements:
        for announcement in group['entries']:
            if announcement['name'] is None:
                announcement['name'] = current_date
    with open("live_ipv4.m3u", "w", encoding="utf-8") as f_m3u_ipv4, \
            open("live_ipv4.txt", "w", encoding="utf-8") as f_txt_ipv4, \
            open("live_ipv6.m3u", "w", encoding="utf-8") as f_m3u_ipv6, \
            open("live_ipv6.txt", "w", encoding="utf-8") as f_txt_ipv6:
        f_m3u_ipv4.write(f"""#EXTM3U x-tvg-url={",".join(f'"{epg_url}"' for epg_url in config.epg_urls)}\n""")
        f_m3u_ipv6.write(f"""#EXTM3U x-tvg-url={",".join(f'"{epg_url}"' for epg_url in config.epg_urls)}\n""")
        for group in config.announcements:
            f_txt_ipv4.write(f"{group['channel']},#genre#\n")
            f_txt_ipv6.write(f"{group['channel']},#genre#\n")
            for announcement in group['entries']:
                f_m3u_ipv4.write(f"""#EXTINF:-1 tvg-id="1" tvg-name="{announcement['name']}" tvg-logo="{announcement['logo']}" group-title="{group['channel']}",{announcement['name']}\n""")
                f_m3u_ipv4.write(f"{announcement['url']}\n")
                f_txt_ipv4.write(f"{announcement['name']},{announcement['url']}\n")
                f_m3u_ipv6.write(f"""#EXTINF:-1 tvg-id="1" tvg-name="{announcement['name']}" tvg-logo="{announcement['logo']}" group-title="{group['channel']}",{announcement['name']}\n""")
                f_m3u_ipv6.write(f"{announcement['url']}\n")
                f_txt_ipv6.write(f"{announcement['name']},{announcement['url']}\n")
        for category, channel_list in template_channels.items():
            f_txt_ipv4.write(f"{category},#genre#\n")
            f_txt_ipv6.write(f"{category},#genre#\n")
            if category in channels:
                for channel_name in channel_list:
                    if channel_name in channels[category]:
                        sorted_urls_ipv4 = [url for url in sort_and_filter_urls(channels[category][channel_name], written_urls_ipv4) if not is_ipv6(url)]
                        sorted_urls_ipv6 = [url for url in sort_and_filter_urls(channels[category][channel_name], written_urls_ipv6) if is_ipv6(url)]
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


def sort_and_filter_urls(urls, written_urls):
    """
    排序和过滤URL
    :param urls: 待排序和过滤的URL列表
    :param written_urls: 已写入的URL集合
    :return: 排序和过滤后的URL列表
    """
    filtered_urls = [
        url for url in sorted(urls, key=lambda u: not is_ipv6(u) if config.ip_version_priority == "ipv6" else is_ipv6(u))
        if url and url not in written_urls and not any(blacklist in url for blacklist in config.url_blacklist)
    ]
    written_urls.update(filtered_urls)
    return filtered_urls


def add_url_suffix(url, index, total_urls, ip_version):
    """
    添加URL后缀
    :param url: 原始URL
    :param index: 当前URL的索引
    :param total_urls: URL总数
    :param ip_version: IP版本
    :return: 添加后缀后的URL
    """
    suffix = f"${ip_version}" if total_urls == 1 else f"${ip_version}•线路{index}"
    base_url = url.split('$', 1)[0] if '$' in url else url
    return f"{base_url}{suffix}"


def write_to_files(f_m3u, f_txt, category, channel_name, index, new_url):
    """
    写入M3U和TXT文件
    :param f_m3u: M3U文件对象
    :param f_txt: TXT文件对象
    :param category: 频道分类
    :param channel_name: 频道名称
    :param index: 当前URL的索引
    :param new_url: 添加后缀后的URL
    """
    logo_url = f"https://gitee.com/IIII-9306/PAV/raw/master/logos/{channel_name}.png"
    f_m3u.write(f"#EXTINF:-1 tvg-id=\"{index}\" tvg-name=\"{channel_name}\" tvg-logo=\"{logo_url}\" group-title=\"{category}\",{channel_name}\n")
    f_m3u.write(new_url + "\n")
    f_txt.write(f"{channel_name},{new_url}\n")


async def speed_test_all_urls(all_urls):
    """
    对所有URL进行测速
    :param all_urls: 所有URL列表
    :return: 测速结果列表
    """
    results = await batch_speed_test(all_urls)
    return results


if __name__ == "__main__":
    template_file = "demo.txt"
    channels, template_channels = filter_source_urls(template_file)
    all_urls = [url for category in channels.values() for urls in category.values() for url in urls]
    loop = asyncio.get_event_loop()
    speed_test_results = loop.run_until_complete(speed_test_all_urls(all_urls))
    updateChannelUrlsM3U(channels, template_channels)
