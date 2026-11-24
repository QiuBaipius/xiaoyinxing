"""站点与栏目配置：定义爬取入口、栏目分类、受众与详情页规则。

分级 RAG 的「部门/主题」元数据在此落地，采集到的每篇文档都会被
打上 category（一级主题）+ audience（受众）标签，供 L0 路由过滤使用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Column:
    name: str              # 栏目名（展示）
    url: str               # 列表页 URL
    category: str          # 一级分类（路由用）
    audience: str = "all"  # student / teacher / all
    list_href_pattern: str = r"content_(\d+)\.html"  # 列表内详情链接匹配


@dataclass
class Site:
    key: str               # 站点唯一标识
    name: str              # 站点名（来源展示）
    base_url: str          # 域名（相对链接拼接用）
    homepage: str          # 首页，用于兜底抽取
    columns: List[Column] = field(default_factory=list)


# 分类统一词汇表（L0 路由 & 前端展示共用）
CATEGORY_CN = {
    "policy": "政策制度",
    "notice": "通知公告",
    "news": "新闻动态",
    "course": "课程选课",
    "exam": "考试安排",
    "process": "办事流程",
    "guide": "办事指南",
    "calendar": "校历时间",
    "scholarship": "奖助贷",
    "graduation": "毕业学位",
    "service": "校园服务",
    "general": "其他",
}

# 面向学生的「高频业务流程」关键词路由表（L0 规则分类兜底）
PROCESS_KEYWORDS = {
    "course": ["选课", "课表", "课程安排", "重修", "补修", "辅修", "通识", "教材选用", "学分", "培养方案"],
    "exam": ["考试", "补考", "缓考", "机考", "四六级", "等级考试", "普通话", "成绩", "监考"],
    "process": ["证明", "办理", "申请", "审批", "流程", "盖章", "材料", "学籍", "休学", "复学", "转专业", "退学"],
    "scholarship": ["奖学金", "助学金", "助学贷款", "勤工助学", "困难认定", "学费减免", "资助"],
    "graduation": ["毕业", "学位", "答辩", "毕业论文", "结业", "延期毕业", "双学位"],
    "service": ["图书馆", "校园卡", "一卡通", "宿舍", "食堂", "网络", "邮箱", "教室借用", "校园导航"],
    "calendar": ["校历", "放假", "开学", "军训", "寒暑假", "周次", "作息"],
    "policy": ["规定", "办法", "条例", "细则", "制度", "管理办法", "通知"],
}

SITES: List[Site] = [
    Site(
        key="portal",
        name="东北财经大学门户",
        base_url="https://www.dufe.edu.cn",
        homepage="https://www.dufe.edu.cn/",
        columns=[
            Column("通知公告", "https://www.dufe.edu.cn/r_6.html", "notice", "all"),
            Column("新闻中心", "https://www.dufe.edu.cn/news/", "news", "all"),
        ],
    ),
    Site(
        key="jwc",
        name="东北财经大学教务处",
        base_url="https://jwc.dufe.edu.cn",
        homepage="https://jwc.dufe.edu.cn/",
        columns=[
            Column("通知公告", "https://jwc.dufe.edu.cn/xwsd/tzgg/", "notice", "all"),
            Column("新闻速递", "https://jwc.dufe.edu.cn/xwsd/xwsd/", "news", "all"),
            Column("规章制度", "https://jwc.dufe.edu.cn/gzzd/", "policy", "all"),
            Column("学生办事指南", "https://jwc.dufe.edu.cn/bszn/student/", "guide", "student"),
            Column("教师办事指南", "https://jwc.dufe.edu.cn/bszn/teacher/", "guide", "teacher"),
            Column("学期课表", "https://jwc.dufe.edu.cn/xqkb/", "course", "student"),
            Column("下载专区", "https://jwc.dufe.edu.cn/xzzq/", "service", "all"),
        ],
    ),
]
