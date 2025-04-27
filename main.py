import requests
import os
from config import source_urls, url_blacklist

def is_blacklisted(url):
    # 检查URL是否在黑名单中
    for blacklisted in url_blacklist:
        if blacklisted in url:
            return True
    return False

def fetch_stream_info(url):
    # 从URL获取直播源信息
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.text
        else:
            print(f"Failed to fetch {url}. Status code: {response.status_code}")
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
    return None

def parse_stream_info(info):
    # 解析直播源信息，提取频道名称、图标和组信息
    lines = info.splitlines()
    streams = []
    current_stream = {}
    for line in lines:
        if line.startswith("#EXTINF:"):
            parts = line.split(",", 1)
            meta = parts[0].split("tvg-logo=")
            if len(meta) > 1:
                logo = meta[1].split('"')[1]
            else:
                logo = ""
            group = ""
            if "group-title=" in meta[0]:
                group = meta[0].split('group-title="')[1].split('"')[0]
            name = parts[1]
            current_stream = {
                "name": name,
                "logo": logo,
                "group": group
            }
        elif line.startswith("http"):
            if not is_blacklisted(line):
                current_stream["url"] = line
                streams.append(current_stream)
            current_stream = {}
    return streams

def generate_m3u(streams, output_path):
    # 生成M3U格式的直播列表
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for stream in streams:
            f.write(f'#EXTINF:-1 tvg-logo="{stream["logo"]}" group-title="{stream["group"]}",{stream["name"]}\n')
            f.write(f'{stream["url"]}\n')

def generate_txt(streams, output_path):
    # 生成TXT格式的直播列表
    with open(output_path, "w", encoding="utf-8") as f:
        for stream in streams:
            f.write(f'频道名称: {stream["name"]}\n')
            f.write(f'图标: {stream["logo"]}\n')
            f.write(f'组信息: {stream["group"]}\n')
            f.write(f'直播地址: {stream["url"]}\n')
            f.write("-" * 50 + "\n")

def main():
    all_streams = []
    # 遍历所有直播源URL
    for url in source_urls:
        info = fetch_stream_info(url)
        if info:
            streams = parse_stream_info(info)
            all_streams.extend(streams)

    # 创建output文件夹
    if not os.path.exists("output"):
        os.makedirs("output")

    # 生成M3U和TXT文件
    generate_m3u(all_streams, "output/iptv.m3u")
    generate_txt(all_streams, "output/iptv.txt")

if __name__ == "__main__":
    main()
