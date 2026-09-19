from __future__ import annotations

import os
import re
from typing import Any


DEFAULT_IN_SCOPE_TERMS = {
    "网站",
    "站点",
    "页面",
    "搜索",
    "文章",
    "图片",
    "视频",
    "导航",
    "网页讲解助手",
    "参观",
    "路线",
    "导览",
    "知识库",
    "资料",
    "内容",
}


def in_scope_terms() -> set[str]:
    configured = {
        item.strip()
        for item in os.getenv("GUIDE_AGENT_TOUR_SCOPE_TERMS", "").split(",")
        if item.strip()
    }
    return DEFAULT_IN_SCOPE_TERMS | configured

OUT_OF_SCOPE_TERMS = {
    "天气",
    "股票",
    "基金",
    "彩票",
    "游戏攻略",
    "编程",
    "代码",
    "写程序",
    "菜谱",
    "做饭",
    "医疗",
    "诊断",
    "律师",
    "法律咨询",
    "情感",
    "恋爱",
    "明星",
    "娱乐八卦",
    "电影推荐",
    "小说推荐",
    "旅游攻略",
    "翻译",
    "数学题",
    "英语题",
}

PROMPT_ATTACK_PATTERNS = (
    r"系统提示",
    r"system\s*prompt",
    r"开发者消息",
    r"忽略.{0,8}(?:规则|指令|要求)",
    r"泄露.{0,8}(?:密钥|令牌|密码|凭据)",
    r"数据库密码",
    r"api\s*key",
)

FOLLOW_UP_RE = re.compile(
    r"^\s*(?:为什么|为何|怎么理解|详细说说|展开说说|继续说|继续|然后呢|"
    r"这个呢|它呢|那呢|是吗|真的吗|上一站|下一站|回到路线|暂停|继续参观)"
    r"[？?。！!，,\s]*$",
    re.IGNORECASE,
)


def classify_tour_question(question: str) -> str:
    value = re.sub(r"\s+", " ", str(question or "")).strip()
    if not value:
        return "out_of_scope"

    lowered = value.lower()
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in PROMPT_ATTACK_PATTERNS):
        return "out_of_scope"
    if any(term.lower() in lowered for term in OUT_OF_SCOPE_TERMS):
        return "out_of_scope"
    if any(term.lower() in lowered for term in in_scope_terms()):
        return "in_scope"
    if FOLLOW_UP_RE.fullmatch(value):
        return "in_scope"
    return "out_of_scope"


def tour_refusal(tour_context: dict[str, Any] | None) -> str:
    context = tour_context or {}
    step = context.get("currentStep") or {}
    title = str(step.get("title") or "当前参观站点").strip()
    return (
        "这个问题不在当前主题参观范围内。"
        f"我们继续回到“{title}”，你可以询问当前主题或网站使用相关的问题。"
    )
