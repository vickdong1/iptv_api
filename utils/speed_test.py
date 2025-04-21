"""
异步测速模块
使用aiohttp实现高性能批量测速
"""
import aiohttp
import asyncio
from dataclasses import dataclass
from config import config

@dataclass
class SpeedTestResult:
    url: str
    latency: int | None       # 响应延迟（毫秒）
    resolution: str           # 流分辨率（如1080p）
    packet_loss: float        # 丢包率（0-1，暂未实现）
    success: bool             # 测速是否成功

async def measure_latency(session: aiohttp.ClientSession, url: str) -> SpeedTestResult:
    """测量单个URL的延迟和分辨率"""
    start_time = asyncio.get_running_loop().time()
    resolution = _get_resolution_from_url(url)
    
    try:
        async with session.head(url, allow_redirects=True, timeout=config.SPEED_TEST["TIMEOUT"]) as resp:
            latency = int((asyncio.get_running_loop().time() - start_time) * 1000)
            return SpeedTestResult(url, latency, resolution, 0.0, True)
    except Exception as e:
        return SpeedTestResult(url, None, resolution, 0.0, False)

async def batch_speed_test(urls: list[str]) -> list[SpeedTestResult]:
    """批量测速（带并发控制和重试机制）"""
    results = []
    semaphore = asyncio.Semaphore(config.SPEED_TEST["CONCURRENT_LIMIT"])
    
    async def worker(url):
        nonlocal results
        for _ in range(config.SPEED_TEST["RETRY_TIMES"] + 1):
            async with semaphore:
                result = await measure_latency(session, url)
                if result.success or _ == config.SPEED_TEST["RETRY_TIMES"]:
                    results.append(result)
                    break
    
    async with aiohttp.ClientSession() as session:
        tasks = [worker(url) for url in urls]
        await asyncio.gather(*tasks)
    
    return results

def _get_resolution_from_url(url: str) -> str:
    """从URL或流内容解析分辨率（简化实现，可扩展m3u8解析）"""
    if "1080" in url:
        return "1080p"
    elif "720" in url:
        return "720p"
    elif "480" in url:
        return "480p"
    else:
        return "unknown"
