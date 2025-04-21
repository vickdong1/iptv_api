"""
主程序入口
执行数据抓取、测速、筛选、生成输出文件全流程
"""
import asyncio
import logging
from collections import defaultdict
from config import (
    SOURCE_URLS, OUTPUT_FILES, 
    SPEED_TEST, IP_VERSION_PRIORITY,
    EPG_URLS, LOGO_BASE_URL
)
from utils.parser import parse_template, parse_source_content
from utils.speed_test import batch_speed_test, SpeedTestResult

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("auto_iptv.log", mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

async def fetch_source(url: str) -> dict:
    """抓取单个数据源并解析"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                content = await response.text()
                source_type = "m3u" if ".m3u" in url else "txt"
                return parse_source_content(content, source_type)
    except Exception as e:
        logging.error(f"抓取 {url} 失败: {str(e)}")
        return {}

async def fetch_all_sources() -> dict:
    """批量抓取所有数据源"""
    tasks = [fetch_source(url) for url in SOURCE_URLS]
    results = await asyncio.gather(*tasks)
    return {url: res for url, res in zip(SOURCE_URLS, results) if res}

def merge_channels(all_sources: dict) -> dict:
    """合并多源频道数据"""
    merged = defaultdict(lambda: defaultdict(list))  # 分类->频道->URL列表
    
    for source_url, channels in all_sources.items():
        for channel_name, ip_channels in channels.items():
            for ip_version, urls in ip_channels.items():
                merged[channel_name][ip_version].extend(urls)
    
    # 去重（保留不同IP版本的重复URL）
    for ch_name, ip_channels in merged.items():
        for ip_version, urls in ip_channels.items():
            merged[ch_name][ip_version] = list(dict.fromkeys(urls))  # 保持顺序去重
    
    return merged

async def process_speed_test(channels: dict) -> dict:
    """对所有频道URL执行测速"""
    if not SPEED_TEST["ENABLED"]:
        return channels
    
    all_urls = []
    for ch_name, ip_channels in channels.items():
        for ip_version, urls in ip_channels.items():
            all_urls.extend(urls)
    
    logging.info(f"开始测速，共{len(all_urls)}个URL")
    test_results = await batch_speed_test(all_urls)
    
    # 按URL分组结果
    result_map = {r.url: r for r in test_results}
    
    # 重组数据结构：分类->频道->带性能的URL列表
    processed = defaultdict(lambda: defaultdict(list))
    for ch_name, ip_channels in channels.items():
        for ip_version, urls in ip_channels.items():
            for url in urls:
                result = result_map.get(url, SpeedTestResult(url, None, "unknown", 0.0, False))
                processed[ch_name][ip_version].append(result)
    
    return processed

def filter_and_sort_channels(processed_channels: dict) -> dict:
    """根据性能数据过滤和排序"""
    filtered = defaultdict(list)
    
    for ch_name, ip_channels in processed_channels.items():
        # 合并所有IP版本的结果
        all_results = []
        for ip_version in IP_VERSION_PRIORITY:  # 按优先级顺序处理
            for res in ip_channels.get(ip_version, []):
                if res.latency is not None and res.latency <= SPEED_TEST["MAX_LATENCY"]:
                    all_results.append((res, ip_version))
        
        # 排序规则：延迟升序 > 分辨率降序 > IP优先级（IPV6优先）
        all_results.sort(key=lambda x: (
            x[0].latency or float('inf'),            # 延迟优先，失败项排最后
            -int(x[0].resolution.split('p')[0]),     # 分辨率降序
            IP_VERSION_PRIORITY.index(x[1])           # IP版本优先级
        ))
        
        # 保留前3个最佳源（可配置）
        best_sources = all_results[:3]
        filtered[ch_name] = [res[0] for res in best_sources]
    
    return filtered

def generate_m3u_file(channels: dict, template_categories: dict) -> None:
    """生成M3U格式输出文件"""
    with open(OUTPUT_FILES["M3U_IPV6"], "w", encoding="utf-8") as f_m3u:
        f_m3u.write(f"#EXTM3U x-tvg-url={','.join(f'"{url}"' for url in EPG_URLS)}\n")
        
        for category, channel_names in template_categories.items():
            f_m3u.write(f"\n#EXTXGROUP:{category}\n")
            for ch_name in channel_names:
                sources = channels.get(ch_name, [])
                if not sources:
                    continue
                
                for idx, source in enumerate(sources, 1):
                    logo_url = f"{LOGO_BASE_URL}{ch_name.replace(' ', '_')}.png"
                    meta = f"延迟:{source.latency}ms 分辨率:{source.resolution}"
                    
                    f_m3u.write(f'#EXTINF:-1,{ch_name} ({idx})\n')
                    f_m3u.write(f'#EXTLOGO:{logo_url}\n')
                    f_m3u.write(f'#EXTVLCOPT:network-caching=3000\n')
                    f_m3u.write(f"{source.url}?t={int(datetime.now().timestamp())}\n")

def generate_txt_file(channels: dict) -> None:
    """生成TXT格式输出文件（包含性能数据）"""
    with open(OUTPUT_FILES["TXT_IPV6"], "w", encoding="utf-8") as f_txt:
        for ch_name, sources in channels.items():
            for source in sources:
                f_txt.write(f"{ch_name},{source.url},{source.latency},{source.resolution}\n")

async def main():
    logging.info("开始执行IPTV频道生成流程")
    
    # 1. 解析模板文件
    template_categories = parse_template(config.TEMPLATE_FILE)
    logging.info(f"解析模板成功，获取{len(template_categories)}个分类")
    
    # 2. 抓取所有数据源
    all_sources = await fetch_all_sources()
    logging.info(f"成功抓取{len(all_sources)}个数据源")
    
    # 3. 合并多源数据
    merged_channels = merge_channels(all_sources)
    logging.info(f"合并后得到{len(merged_channels)}个频道")
    
    # 4. 执行测速和性能分析
    processed_channels = await process_speed_test(merged_channels)
    
    # 5. 动态筛选和排序
    optimized_channels = filter_and_sort_channels(processed_channels)
    
    # 6. 生成输出文件
    generate_m3u_file(optimized_channels, template_categories)
    generate_txt_file(optimized_channels)
    
    logging.info("流程完成，输出文件已生成")

if __name__ == "__main__":
    asyncio.run(main())
