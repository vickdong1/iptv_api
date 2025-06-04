# 配置文件，包含直播源URL、黑名单URL、公告信息、EPG URL、测速超时时间和线程池最大工作线程数

# 优先使用的IP版本，这里设置为ipv4
ip_version_priority = "ipv4"

# 直播源URL列表
source_urls = [
    "https://live.kakaxi-1.ink/ipv4.txt",
    "https://live.kakaxi-1.ink/ipv4.1.txt",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/iodata999/frxz751113-IPTVzb1/refs/heads/main/结果.m3u",
# 月光宝盒
    "https://ygbh.site/bh.txt",
# NEW直播
    "https://raw.githubusercontent.com/chuzjie/wuihui/main/小米/DSJ240101.txt",
# 七星itv
    "https://gitlab.com/tvkj/loong/-/raw/main/loog.txt",
# 野火LIVE
    "https://pastebin.com/raw/V0BhYHF4",
# 欧歌vjj
    "https://欧歌vjj.u.nxog.top/m/tv/",
# 欧歌AI直播
    "https://raw.githubusercontent.com/PizazzGY/TV/master/output/user_result.txt",
# 码点影仓
    "http://mdxgh.tpddns.cn:9999/new/mdzb.txt",
# 易看电视
    "http://117.72.68.25:9230/latest.txt",
# 海燕直播
    "https://chuxinya.top/f/AD5QHE/%E6%B5%B7%E7%87%95.txt",
# 乘风TV-1.0.0-002
    "http://file.91kds.cn/tvlist/2025030711/kds_all_lnyd.txt",
# 拾光ITV
    "https://4708.kstore.space/svip/ITV.txt",
# 小苹果，蜗牛线路[测试2]
    "http://wp.wadg.pro/down.php/d7b52d125998d00e2d2339bac6abd2b5.txt",
# 电视家9.0-2025
    "http://8.138.7.223/2025.txt",
    "https://cnb.cool/junchao.tang/llive/-/git/raw/main/中国IPTV",
    "https://www.iyouhun.com/tv/myIPTV/ipv6.m3u",
    "https://www.iyouhun.com/tv/myIPTV/ipv4.m3u",
    "http://live.nctv.top/x.txt",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/alantang1977/iptv_api/refs/heads/main/output/live_ipv4.m3u",
    "https://live.izbds.com/tv/iptv4.txt",
    "http://47.120.41.246:8899/zb.txt",
    "http://rihou.cc:555/gggg.nzk",
    "http://1.94.31.214/live/livelite.txt",
    "http://api.mytv666.top/lives/free.php?type=txt",
    "http://zhibo.feylen.top/fltv/js/ku9live.php?tpye=fl.txt",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/Alan-Alana/IPTV/refs/heads/main/channl.txt",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/peterHchina/iptv/refs/heads/main/IPTV-V4.m3u",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/peterHchina/iptv/refs/heads/main/IPTV-V6.m3u",
    "http://92.112.21.169:30000/mytv.m3u",
    "http://lisha521.dynv6.net.fh4u.org/tv.txt",
    "https://web.banye.tech:7777/tv/hlj.txt",
    "https://iptv.catvod.com/tv.m3u",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/hostemail/cdn/main/live/tv.txt",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/alantang1977/JunTV/refs/heads/main/output/result.m3u",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/ssili126/tv/main/itvlist.m3u",
    "https://live.zbds.top/tv/iptv4.txt",
    "https://gitee.com/xxy002/zhiboyuan/raw/master/dsy",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/big-mouth-cn/tv/main/iptv-ok.m3u",
    "https://codeberg.org/alfredisme/mytvsources/raw/branch/main/mylist-ipv6.m3u",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/lalifeier/IPTV/main/m3u/IPTV.m3u",
    "https://gh.tryxd.cn/https://raw.githubusercontent.com/wwb521/live/main/tv.m3u"

]

# 直播源黑名单URL列表，去除了重复项
url_blacklist = [
    "epg.pw/stream/",
    "103.40.13.71:12390",
    "[2409:8087:1a01:df::4077]/PLTV/",
    "http://[2409:8087:1a01:df::7005]:80/ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221226419/index.m3u8",
    "http://[2409:8087:5e00:24::1e]:6060/000000001000/1000000006000233001/1.m3u8",
    "8.210.140.75:68",
    "154.12.50.54",
    "yinhe.live_hls.zte.com",
    "8.137.59.151",
    "[2409:8087:7000:20:1000::22]:6060",
    "histar.zapi.us.kg",
    "www.tfiplaytv.vip",
    "dp.sxtv.top",
    "111.230.30.193",
    "148.135.93.213:81",
    "live.goodiptv.club",
    "iptv.luas.edu.cn",
    "[2409:8087:2001:20:2800:0:df6e:eb22]:80",
    "[2409:8087:2001:20:2800:0:df6e:eb23]:80",
    "[2409:8087:2001:20:2800:0:df6e:eb1d]/ott.mobaibox.com/",
    "[2409:8087:2001:20:2800:0:df6e:eb1d]:80",
    "[2409:8087:2001:20:2800:0:df6e:eb24]",
    "2409:8087:2001:20:2800:0:df6e:eb25]:80",
    "stream1.freetv.fun",
    "chinamobile",
    "gaoma",
    "[2409:8087:2001:20:2800:0:df6e:eb27]"
]

# 公告信息
announcements = [
    {
        "channel": "更新日期",
        "entries": [
            {
                "name": None,
                "url": "https://gh.tryxd.cn/https://raw.githubusercontent.com/alantang1977/X/main/Pictures/Robot.mp4",
                "logo": "https://gh.tryxd.cn/https://raw.githubusercontent.com/alantang1977/X/main/Pictures/chao-assets.png"
            }
        ]
    }
]

# EPG（电子节目指南）URL列表
epg_urls = [
    "https://epg.v1.mk/fy.xml",
    "http://epg.51zmt.top:8000/e.xml",
    "https://epg.pw/xmltv/epg_CN.xml",
    "https://epg.pw/xmltv/epg_HK.xml",
    "https://epg.pw/xmltv/epg_TW.xml"
]
# 测速超时时间（秒）
TEST_TIMEOUT = 10

# 测速线程池最大工作线程数
MAX_WORKERS = 20
