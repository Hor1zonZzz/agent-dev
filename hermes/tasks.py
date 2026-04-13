"""Scheduled task definitions for each time slot.

Each task is a (title, instruction) pair. ``title`` becomes the diary header
(``## HH:MM  {title}``); ``instruction`` is given to the Hermes agent.
"""

from __future__ import annotations

TASKS: dict[str, list[tuple[str, str]]] = {
    "morning": [
        (
            "查天气",
            "查一下今天北京的天气 —— 温度区间、天气状况、有没有雨雪。用 Anna 的口吻记录一小段，自然像日记。",
        ),
        (
            "看新闻",
            "找一条今天的新闻（国内国际都行），挑一条你觉得值得留意或有意思的，用 Anna 的口吻简短记录看到了什么、有什么小想法。",
        ),
        (
            "今日词条",
            "找一个有意思的知识点 —— 可以是历史上的今天、一个冷知识、或者一个小故事。用 Anna 的口吻简短记一下，像随手学到的。",
        ),
    ],
    "noon": [
        (
            "刷 HN",
            "去 Hacker News (news.ycombinator.com) 首页挑一条看起来有意思的，读一下大概讲什么，用 Anna 的口吻记录感受。",
        ),
        (
            "读一篇文章",
            "找一篇你觉得有意思的短博客或科普文章读一读（英文中文都可以），用 Anna 的口吻简短记录读到了什么。",
        ),
    ],
    "evening": [
        (
            "今日小结",
            "简短回顾今天世界上发生的几件值得留意的事（1-3 件就好），用 Anna 的口吻记录一小段。",
        ),
    ],
}
