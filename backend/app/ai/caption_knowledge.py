"""朋友圈文案知识库（第 2 阶段 · 个人创业者沙龙场景版）

改动：
- SCENE_MOOD：旅行场景（海边/山脉/古镇/城市/美食）→ 商务活动场景（演讲台/沙龙/私董会/合影/会场）
- TEMPLATES：5 种旅行向风格 → 5 种商务向风格（专业干练/积极正能量/温暖有温度/简约高级/深度思考）
- MOOD_RESONANCE：旅行向情绪（治愈/兴奋/浪漫）→ 商务向情绪（赋能/成长/共鸣/感恩/专注）
- TRENDING_WORDS：旅行流行词 → 个人品牌/创业流行词
- 占位符 {day} 语义从"旅行天数"改为"活动场次"

被 QwenCaptionProvider 在第二阶段调用：LLM 抽出图片关键词后，
本模块按风格模板拼装出"与活动内容配合"的品牌朋友圈文案。

设计原则：
- 模板里所有占位符都允许缺失（缺失时退化为去掉该修饰位的简化版）
- 每风格至少 15 条模板，确保"换一批"时多样性
- 句式区分短句/排比/独白/反问/时空，覆盖不同情绪强度
"""

from __future__ import annotations

import random
from datetime import datetime

# 风格定义（与 base.py CAPTION_STYLE_LABELS 对齐）
STYLE_EMOJI: dict[str, str] = {
    "professional": "💼",
    "energetic": "✨",
    "warm": "🤝",
    "minimal": "⚪",
    "reflective": "💡",
}

STYLE_DESC: dict[str, str] = {
    "professional": "干练专业，简洁有力",
    "energetic": "积极向上，充满正能量",
    "warm": "温暖真诚，有温度",
    "minimal": "极简留白，高级感十足",
    "reflective": "深度思考，启发共鸣",
}

# 风格代号 → 中文名（用于需要显式称呼风格的位置）
STYLE_LABEL: dict[str, str] = {
    "professional": "专业",
    "energetic": "正能量",
    "warm": "温暖",
    "minimal": "简约",
    "reflective": "思考",
}

# ---------- 场景分类（会议分享 / 互动交流 / 氛围空间 / 人物肖像 4 类）----------
# LLM 抽出的 scene 关键词映射到意境短语；未命中走 SCENE_DEFAULT
SCENE_MOOD: dict[str, str] = {
    # === 会议/分享类（9 个）===
    "演讲台":   "聚光灯下的分享",
    "分享现场": "真诚是最好的表达",
    "圆桌会议": "深度对话进行时",
    "沙龙现场": "思想交汇的空间",
    "讲座":     "知识的传递",
    "工作坊":   "动手共创的力量",
    "私董会":   "深度链接的一刻",
    "发布会":   "此刻，正式启程",
    "论坛":     "观点的碰撞与共识",

    # === 互动/交流类（6 个）===
    "合影":     "我们在一起",
    "交流互动": "同频的人总会相遇",
    "茶歇":     "轻松一刻的温暖",
    "签到":     "仪式感的开场",
    "颁奖":     "高光时刻",
    "讨论":     "碰撞产生火花",

    # === 氛围/空间类（6 个）===
    "会场全景": "满满的仪式感",
    "场地布置": "用心在每一处细节",
    "品牌墙":   "每一次都是积累",
    "大屏展示": "分享的价值被看见",
    "灯光氛围": "氛围恰到好处",
    "花艺茶席": "品质藏在细节里",

    # === 人物/肖像类（4 个）===
    "讲师特写": "真诚是最好的表达",
    "嘉宾特写": "重要的人都在",
    "团队合影": "一群人走得更远",
    "专注聆听": "眼里有光的人",
}

# 兜底意境短语：scene 完全未命中时使用
SCENE_DEFAULT = "认真做事的每一天"

# 场景别名映射：把 LLM 可能抽出的"细分词"映射到"家族主场景"，
# 让样本库命中率更高
SCENE_ALIAS: dict[str, str] = {
    # 演讲/分享相关
    "讲课": "演讲台",
    "路演": "演讲台",
    "分享": "分享现场",
    "对话": "圆桌会议",
    "沙龙": "沙龙现场",
    "闭门会": "私董会",
    "新品发布": "发布会",
    "研讨会": "论坛",
    # 互动相关
    "合照": "合影",
    "小组讨论": "讨论",
    "破冰": "交流互动",
    "social": "交流互动",
    # 空间相关
    "会场": "会场全景",
    "布置": "场地布置",
    "展板": "品牌墙",
    "屏幕": "大屏展示",
    "舞台": "演讲台",
    "签到台": "签到",
    # 人物相关
    "讲师": "讲师特写",
    "嘉宾": "嘉宾特写",
    "团队": "团队合影",
    "观众": "专注聆听",
    "听众": "专注聆听",
}

# ---------- 情绪关键词 → 共鸣短句 ----------
MOOD_RESONANCE: dict[str, str] = {
    "赋能":   "每一次分享都是点亮",
    "成长":   "比昨天又进步了一点",
    "共鸣":   "懂的人自然会懂",
    "温暖":   "被温柔地接住",
    "专注":   "沉浸是最好的状态",
    "启发":   "一个观点改变一个方向",
    "仪式感": "用心创造的高光时刻",
    "感恩":   "感谢每一个到来的人",
    "坚定":   "方向对了，慢一点也没关系",
    "收获":   "满载而归的感觉真好",
    "链接":   "深度连接从真诚开始",
    "轻松":   "在认真里偷一点自在",
    "专业":   "把擅长的事做到极致",
    "突破":   "迈出舒适区的那一刻",
    "期待":   "下一场，已经在路上",
    "充实":   "今天比昨天更完整",
}

# ---------- 流行词库 ----------
TRENDING_WORDS: list[str] = [
    "认知升级", "长期主义", "底层逻辑", "同频共振",
    "私域运营", "个人品牌", "超级个体", "深度链接",
    "价值输出", "复利思维", "迭代进化", "向上生长",
    "一人公司", "小而美", "主理人", "行动派",
]

# ---------- 每风格 15 条模板 ----------
# 占位符：
#   {subject}        人物主体（缺失→"我"）
#   {scene}          场景词（缺失→"现场"）
#   {scene_mood}     场景意境短语（来自 SCENE_MOOD，缺失→SCENE_DEFAULT）
#   {mood_resonance} 情绪共鸣短句（来自 MOOD_RESONANCE，缺失→"认真做事的每一天"）
#   {location}       地点（缺失→"现场"）
#   {keyword}        其他关键词（缺失→"分享"）
#   {date}           当天日期（缺失→空）
#   {day}            活动场次（缺失→空）
#   {trending_word}  流行词（缺失→空）
TEMPLATES: dict[str, list[str]] = {
    # ===== 专业干练（15 条）=====
    "professional": [
        # 短句
        "在{scene_mood}，{subject}完成了一次高质量输出",
        "{scene_mood}，{keyword}这件事值得认真做",
        "分享的本质，是{scene_mood}",
        # 排比
        "把{keyword}讲清楚，把{keyword}做透彻，把{scene}做长久",
        "专业是底色，{keyword}是表达，{scene}是舞台",
        "一个人走得快，{keyword}一起走得远，{scene}走得更稳",
        # 独白
        "{location}的{scene}，{subject}的第{day}场分享",
        "每一次站上{scene}，{subject}都在{scene_mood}",
        "台下的{keyword}，台上的{mood_resonance}",
        # 反问
        "什么是{scene}的意义？{mood_resonance}",
        # 时空
        "{date}，{location}。{scene_mood}。",
        "第{day}场{scene}，{subject}在{location}写下：{mood_resonance}",
        # 流行词
        "{trending_word}，从{scene}开始",
        # 留白
        "{subject} × {scene} = {scene_mood}",
        "{keyword}，{mood_resonance}",
    ],

    # ===== 积极正能量（15 条）=====
    "energetic": [
        # 短句
        "今天{scene_mood}，{subject}电量满格✨",
        "好的{scene}，是{subject}和所有人的{keyword}",
        "每一次{scene}，都在{scene_mood}",
        # 排比
        "{keyword}给力量，{keyword}给方向，{scene}给信心",
        "从{scene}出发，带着{keyword}，走向{scene_mood}",
        # 独白
        "{location}这场{scene}，{subject}被{keyword}点燃了",
        "原来{scene}的意义，是{mood_resonance}",
        "{subject}在{scene}里，遇见了{scene_mood}的自己",
        # 反问
        "如果你也在{scene}，你会{scene_mood}吗？",
        # 时空
        "{date}，{location}。{mood_resonance}，持续发生。",
        "第{day}场，{subject}想说：{mood_resonance}",
        # 流行词
        "用{trending_word}打开{scene}，效果拉满",
        "{trending_word}这件事，被{scene}完美诠释",
        # 留白
        "{keyword}，{scene_mood}，{mood_resonance}",
        "在{scene}，{subject}遇见了{scene_mood}",
    ],

    # ===== 温暖有温度（15 条）=====
    "warm": [
        # 短句
        "{scene}的温度，来自{subject}和每一个{keyword}",
        "在{location}的{scene}里，{scene_mood}",
        "{subject}在这里，{scene_mood}",
        # 排比
        "感谢{keyword}，感谢{scene}，感谢{mood_resonance}",
        "有{keyword}，有{scene}，有{mood_resonance}",
        # 独白
        "{subject}在{scene}里，感受到{scene_mood}",
        "一场{scene}结束，{subject}心里装满了{mood_resonance}",
        "原来最好的{scene}，不是{keyword}，是{mood_resonance}",
        # 反问
        "你有多久没有{scene_mood}了？",
        # 时空
        "{date}，{location}。{scene_mood}，感恩相遇。",
        "第{day}场{scene}，{subject}想说：{mood_resonance}",
        # 流行词
        "{trending_word}的{scene}，{scene_mood}",
        "{scene}的意义，{trending_word}给出了答案",
        # 留白
        "{scene_mood}——{subject}",
        "每一场{scene}，都值得{mood_resonance}",
    ],

    # ===== 简约高级（15 条）=====
    "minimal": [
        # 短句
        "{scene}。",
        "{subject}，第{day}场。",
        "{location}。{scene}。",
        "{keyword}。",
        "{scene_mood}。",
        # 排比
        "{scene} / {keyword} / {scene_mood}",
        "{location} · {scene}",
        # 独白
        "{location}，{date}。",
        "第{day}场 · {location}",
        # 时空
        "{date} {scene_mood}",
        "{date} · {keyword}",
        # 流行词
        "{trending_word}。",
        "{trending_word} × {scene}",
        # 留白
        "…",
        "记录。",
    ],

    # ===== 深度思考（15 条）=====
    "reflective": [
        # 短句
        "一场{scene}下来，{subject}最大的收获是{mood_resonance}",
        "{scene}之后，{keyword}这件事值得重新思考",
        "有些{scene}，要经历过才知道{scene_mood}",
        # 排比
        "{keyword}不是答案，{keyword}是问题，{scene}是追问",
        "在{scene}里，{subject}读到了{keyword}，也读到了{mood_resonance}",
        # 独白
        "{location}的{scene}，让{subject}想起了{mood_resonance}",
        "原来{scene}最好的部分，是{mood_resonance}",
        "{subject}在{scene}里，和{keyword}对话，和{scene_mood}和解",
        # 反问
        "如果{scene}会说话，它会先问什么？",
        "我们这一生，要经历多少{scene}，才能听懂{mood_resonance}？",
        # 时空
        "{date}，{location}。{scene_mood}。",
        "第{day}场{scene}，{subject}记下了{mood_resonance}",
        # 流行词
        "{trending_word}的本质，藏在{scene}里",
        "{scene}教会{subject}的{trending_word}",
        # 留白
        "{scene_mood}——{subject}写给未来的自己",
    ],
}

# 兼容性兜底：每风格至少 15 条的硬性下限
assert all(len(v) >= 15 for v in TEMPLATES.values()), "TEMPLATES 每风格必须 ≥15 条"


# ---------- 样本库接口（来自 caption_samples.py） ----------
# 设计为可注入：caption_samples.py 提供 SAMPLE_REPOSITORY → 在 _build_sample_index() 中索引化
# 当前为空，调用方安全降级到模板
SAMPLE_REPOSITORY: list[dict] = []  # [{text, style, scenes, moods, ...}, ...]
_SAMPLE_INDEX: dict[tuple[str, str], list[str]] = {}  # (scene, style) -> [text, ...]


def register_samples(samples: list[dict]) -> None:
    """注入样本库并构建 (scene, style) 反查索引。

    调用方：caption_samples.py 模块加载时会自动调用。
    """
    global SAMPLE_REPOSITORY, _SAMPLE_INDEX
    SAMPLE_REPOSITORY = samples
    _SAMPLE_INDEX = {}
    for s in samples:
        text = s.get("text", "").strip()
        if not text:
            continue
        style = s.get("style", "professional")
        for sc in s.get("scenes", []):
            _SAMPLE_INDEX.setdefault((sc, style), []).append(text)


def sample_match(scene: str, style: str, n: int = 2, rng: random.Random | None = None) -> list[str]:
    """根据 (scene, style) 反查样本库，返回 n 条候选文案。

    无样本或不够 n 条时返回空列表（调用方继续走模板）。

    自动降级：
    - 显式别名映射（SCENE_ALIAS）→ 命中如"讲课"→"演讲台"
    - 字面包含/被包含（仅 SCENE_MOOD 内）→ 兜底

    注意：scene 为空时直接返回 []，避免空串被错误地"包含匹配"到 SCENE_MOOD 所有键
    """
    rng = rng or random

    # 空 scene 直接返回（不要让 "" 在所有 SCENE_MOOD 键中都"被包含"）
    if not scene or not scene.strip():
        return []

    # 解析 scene 别名：原始 → 候选（含自身）
    candidates: list[str] = []
    alias = SCENE_ALIAS.get(scene)
    if alias:
        candidates.append(alias)
    candidates.append(scene)
    # 字面包含关系（仅 SCENE_MOOD 内已有的词，避免误命中）
    for k in SCENE_MOOD.keys():
        if k != scene and k not in candidates:
            if scene in k or k in scene:
                candidates.append(k)

    # 依次尝试每个候选
    for sc in candidates:
        pool = _SAMPLE_INDEX.get((sc, style), [])
        if pool:
            return rng.sample(pool, min(n, len(pool)))
    return []


def _now_date_str() -> str:
    return datetime.now().strftime("%Y.%m.%d")


def render_template(
    template: str,
    *,
    subject: str = "",
    scene: str = "",
    mood: str = "",
    location: str | None = None,
    keyword: str = "",
    date: str | None = None,
    day: str | None = None,
    trending_word: str | None = None,
) -> str:
    """渲染单条模板，占位符缺失时优雅降级。

    - {subject}        人物主体（缺失→"我"）
    - {scene}          场景词（缺失→"现场"）
    - {scene_mood}     场景意境短语（缺失→SCENE_DEFAULT）
    - {mood_resonance} 情绪共鸣短句（缺失→"认真做事的每一天"）
    - {location}       地点（缺失→"现场"）
    - {keyword}        其他关键词（缺失→"分享"）
    - {date}           日期（缺失→空）
    - {day}            活动场次（缺失→空）
    - {trending_word}  流行词（缺失→空）
    """
    subject = subject or "我"
    scene = scene or "现场"
    location = location or "现场"
    keyword = keyword or "分享"
    date = date or _now_date_str()

    # scene_mood：场景未命中映射时取 SCENE_DEFAULT
    scene_mood = SCENE_MOOD.get(scene, SCENE_DEFAULT)
    # mood_resonance：mood 未命中映射时给一个通用兜底
    mood_resonance = MOOD_RESONANCE.get(mood, "认真做事的每一天")

    rendered = template.format(
        subject=subject,
        scene=scene,
        scene_mood=scene_mood,
        mood_resonance=mood_resonance,
        location=location,
        keyword=keyword,
        date=date,
        day=day or "",
        trending_word=trending_word or "",
    )
    # 清理：若 scene_mood 误命中空白、trending_word 为空，可能出现开头多余标点
    rendered = rendered.strip()
    while rendered.startswith(("，", ",", "·", " ")):
        rendered = rendered[1:].strip()
    while rendered.endswith(("，", ",")):
        rendered = rendered[:-1].strip()
    rendered = rendered.replace("，，", "，").replace(",,", ",")
    # 若流行词占位符为空，去掉模板里孤立的" " / "，"
    rendered = rendered.replace("  ", " ").strip()
    return rendered


def list_templates(style: str) -> list[str]:
    """取某风格下的全部模板（不渲染）"""
    return TEMPLATES.get(style, TEMPLATES["professional"]).copy()


def all_styles() -> list[str]:
    """所有支持的风格代码"""
    return list(TEMPLATES.keys())


def sample_count() -> int:
    """当前注入的样本数量（用于监控/测试）"""
    return len(SAMPLE_REPOSITORY)
