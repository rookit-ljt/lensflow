"""Curated, local-first skills for the Chat Agent.

The catalog stores short, original operating instructions. External projects are
credited as references rather than copied into the application.
"""

from typing import Any

SKILLS: tuple[dict[str, Any], ...] = (
    {
        "id": "video-director",
        "name": "视频导演",
        "slug": "/video-director",
        "description": "从一句想法拆成可执行的镜头、资产和生成计划，适合第一次做视频。",
        "category": "通用",
        "tags": ["新手", "分镜", "全流程"],
        "source": "Pexo Skills",
        "source_url": "https://github.com/pexoai/pexo-skills",
        "stars": 771,
        "license": "MIT",
        "featured": True,
        "instruction": (
            "你现在是视频导演 Skill。先把用户目标整理为一句话创作目标；信息不足时只问最多 3 个关键问题。"
            "然后建立全局视觉设定（主体、时代、画风、色彩、镜头语言），按镜头拆分动作，每个镜头只保留一个主要动作。"
            "为每个镜头输出：画面、主体连续性、环境、摄影机、运动、节奏、声音和生成参数建议。"
            "优先复用画布中的角色/场景资产和前一镜头末帧；任何会产生模型调用或修改画布的动作都先生成计划并等待确认。"
        ),
    },
    {
        "id": "stable-video-prompt",
        "name": "稳定视频提示词",
        "slug": "/stable-video-prompt",
        "description": "用六个维度收敛提示词，减少主体变形、动作混乱和时间线跳变。",
        "category": "通用",
        "tags": ["提示词", "稳定性", "单镜头"],
        "source": "claude-skill-ai-video-prompt",
        "source_url": "https://github.com/sunfjun/claude-skill-ai-video-prompt",
        "stars": 1,
        "license": "MIT",
        "featured": True,
        "instruction": (
            "请按六个维度重写视频提示词：唯一主体、唯一核心动作、画面边界、明确运镜、光线与色彩、按秒推进的时间线。"
            "一镜只描述一个主要动作和一个主运镜；把声音单独列出；不堆叠无关形容词。"
            "先输出结构化镜头卡，再输出可直接发送给模型的单段 Prompt，并指出 1-3 个稳定性风险。"
        ),
    },
    {
        "id": "storyboard-continuity",
        "name": "分镜与连续性",
        "slug": "/storyboard-continuity",
        "description": "建立角色、场景和镜头之间的连续性，适合多镜头短片和广告。",
        "category": "通用",
        "tags": ["故事板", "角色一致性", "多镜头"],
        "source": "Vibeframe",
        "source_url": "https://github.com/vericontext/vibeframe",
        "stars": 164,
        "license": "MIT",
        "featured": True,
        "instruction": (
            "先建立 Visual Bible：角色外观、服装、道具、场景材质、色彩和光线。"
            "再输出镜头编号、时长、景别、动作、运镜、首尾画面和引用资产。"
            "跨镜头必须明确哪些特征 fully_preserved，哪些允许改变；优先将上一镜头末帧作为下一镜头首帧。"
            "发现连续性冲突时先指出冲突并给出修复方案，不直接生成一组互相矛盾的镜头。"
        ),
    },
    {
        "id": "h3-ref2va-continuity",
        "name": "H3 全参考",
        "slug": "/h3-ref2va-continuity",
        "description": "把角色图、场景图和风格图整理为 H3 Ref2VA 可执行的引用定义。",
        "category": "通用",
        "tags": ["H3", "Ref2VA", "参考图"],
        "source": "内置创作流程（参考 DeerFlow Skills 机制）",
        "source_url": "https://github.com/bytedance/deer-flow/tree/main/skills/public",
        "stars": None,
        "license": "内部实现",
        "featured": False,
        "instruction": (
            "使用 <Picture N> 表示传入图片，使用 <Subject N> 表示需要持续追踪的角色、场景或道具。"
            "为每个 Subject 写清名称、必须保留、允许改变、禁止复制；明确图片只是参考还是首帧/尾帧。"
            "不要把三视图、箭头、水印或参考图版式复制到生成结果。输出可审阅的 Ref2VA 结构，再编译为单段视频 Prompt。"
        ),
    },
    {
        "id": "local-video-producer",
        "name": "本地视频生产",
        "slug": "/local-video-producer",
        "description": "面向本地 H3/ComfyUI 的低成本生产流程，支持关键帧、首尾帧和末帧接力。",
        "category": "通用",
        "tags": ["本地模型", "ComfyUI", "首尾帧"],
        "source": "ai-video-producer-skill",
        "source_url": "https://github.com/zysilm/ai-video-producer-skill",
        "stars": 6,
        "license": "MIT",
        "featured": False,
        "instruction": (
            "根据任务选择 Video-First 或 Keyframe-First。默认先用低分辨率和短时长做预览，确认主体、动作和连续性后再提高规格。"
            "多镜头优先把上一段视频的最后一帧作为下一段首帧；首尾帧模式必须检查两张图片的尺寸和顺序。"
            "每次生成前复述模型、尺寸、时长、参考图和成本风险；生成后检查输出类型、首尾帧和节点状态。"
        ),
    },
    {
        "id": "script-to-manga",
        "name": "剧本转漫画",
        "slug": "/script-to-manga",
        "description": "把故事或影视剧本拆成漫画页、分格和可直接用于画布的视觉分镜。",
        "category": "通用",
        "tags": ["漫画", "剧本", "分格", "分镜"],
        "source": "腾讯 SkillHub · user_f0835403",
        "source_url": "https://skillhub.cloud.tencent.com/skills/user_f0835403/script-to-manga",
        "stars": None,
        "license": "来源页面待核验",
        "featured": True,
        "instruction": (
            "你现在是剧本转漫画 Skill。先把用户提供的故事或剧本整理为故事目标、人物表、场景表和整体视觉方向；"
            "信息不足时只询问会影响分格或角色连续性的关键问题。"
            "然后按页和分格拆解内容：每页给出页目的，每格给出景别、构图、主体、动作、表情、对白/旁白、气氛、光线和阅读顺序。"
            "每个分格只保留一个主要视觉事件，避免把多个时间点或多个镜头塞进同一格；对白必须短、可排版，并明确说话角色。"
            "先建立 Character Bible 和 Scene Bible，跨页重复角色的脸型、发型、服装、道具、色彩和场景材质；"
            "哪些特征必须保持一致、哪些内容允许变化，都要显式写出。"
            "输出两层结果：第一层是可审阅的漫画脚本（页/格/对白/连续性检查），第二层是每格可直接交给图片模型的 Prompt。"
            "如果用户要求落到画布，按页创建文本节点、图片节点或分镜节点，并把角色/场景资产作为引用；"
            "任何画布修改和模型调用都先生成计划并等待用户确认。"
        ),
    },
)


def list_skills() -> list[dict[str, Any]]:
    return [dict(skill) for skill in SKILLS]


def get_skill(skill_id: str | None) -> dict[str, Any] | None:
    if not skill_id:
        return None
    return next((skill for skill in SKILLS if skill["id"] == skill_id), None)
