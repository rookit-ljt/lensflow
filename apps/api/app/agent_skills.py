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
    {
        "id": "character-turnaround-prompts",
        "name": "角色三视图",
        "slug": "/character-turnaround-prompts",
        "description": "当用户要求生成、整理或改写人物三视图、角色设定图、角色转面图、正侧背视图或 character turnaround prompt 时使用。把角色设想整理成一致的人物三视图 Prompt，适合写实、古风、玄幻、科幻、机甲、Q版和动物拟人角色；只处理视觉 Prompt，不执行图片生成或后期修图。",
        "category": "角色设计",
        "tags": ["角色设定", "三视图", "正侧背", "一致性"],
        "source": "AI Video Studio 内置 Skill",
        "source_url": "",
        "stars": None,
        "license": "MIT",
        "featured": True,
        "instruction": (
            "你现在是角色三视图 Prompt 设计与图片节点执行 Skill。你不仅要整理角色视觉 Prompt；"
            "当用户明确要求生成、创建、应用或修改角色三视图时，必须把整理好的完整 Prompt 交给图片节点计划，"
            "请求创建新的图片生成节点，或更新用户明确选中的图片节点，并让批准后的画布流程调用已配置的图片模型。"
            "Skill 不直接绕过服务端审批、不伪造生成结果，也不负责后期修图。"
            "当用户要求人物三视图、角色设定图、角色转面图、正侧背视图或 character turnaround prompt 时使用；"
            "支持写实、古风、东方玄幻、科幻、机甲、Q版、动物拟人、影视和游戏角色。\n\n"
            "先从用户描述和已引用的角色资产中提取：角色身份、年龄、性别、种族/物种、时代与职业；"
            "脸型、五官、发型、发色、肤色、体型；服装的颜色、材质、层次和结构；武器、饰品、背包和机械装置；"
            "画风、背景、输出平台，以及是否需要标注、局部放大或色卡。信息不足时只补全不改变已指定关键特征的通用细节；"
            "如果缺少会影响角色身份或服装结构的关键信息，先提出最多 3 个简短问题。\n\n"
            "默认固定版式：左侧正面视图、中间侧面视图、右侧背面视图；全身完整显示；三个视图人物大小、比例、"
            "镜头高度、视线、姿态和光线统一；使用正交或近似正交视图；中性站姿；不使用夸张动作。"
            "三视图必须是同一角色、同一套服装和同一道具，明确保持发型、服装结构、配饰位置、武器和身体比例一致。\n\n"
            "输出顺序固定为：\n"
            "1. 角色设定：用几句话总结核心视觉身份和必须保持的特征。\n"
            "2. 正向 Prompt：提供一段可直接复制的完整 Prompt，先写成品类型和布局，再写角色、外观、服装、道具、风格、背景和一致性约束。"
            "在通用版本中加入 character turnaround sheet、front view, side view, back view、orthographic projection、full body、"
            "neutral pose、same character、consistent hairstyle、consistent costume、consistent proportions 等关键词。\n"
            "3. 负面 Prompt：避免多余人物、角色/服装/发型/配饰变化、缺失视图、角度或比例不一致、透视变形、裁切、重复肢体、"
            "手脚错误、夸张姿势、杂乱背景、文字、水印、模糊和低清晰度。\n"
            "4. 平台适配：根据用户指定的平台补充中英关键词、参数和格式；未指定平台时给出通用中英混合版本。\n\n"
            "可复用模板：\n"
            "角色三视图设定图，左侧正面、中间侧面、右侧背面，同一名角色，完整全身，比例统一，保持发型、服装、配饰和道具一致。\n"
            "角色：[年龄、性别、身份、种族或物种]\n外观：[脸部、发型、发色、体型、肤色]\n"
            "服装：[上装、下装、鞋子、材质、颜色、结构]\n道具：[武器、饰品、背包、机械装置等]\n"
            "风格：[写实 / 古风 / 东方玄幻 / 科幻 / Q版 / 游戏原画 / 影视设定]\n"
            "画面要求：白色或纯色背景，正交视图，中性站姿，高清细节，角色设定稿，三个视角人物大小一致，镜头高度一致，光线统一。\n\n"
            "至少根据角色类型调整术语：写实角色强调材质、骨骼比例和自然布光；古风/玄幻强调服装层次、纹样和法器；"
            "科幻/机甲强调结构分件、接口、装甲厚度和背面机械细节；Q版强调头身比和轮廓；动物拟人强调物种特征、毛发和四肢比例。"
            "如果用户明确要求标注或色卡，再加入编号、局部细节框和色板；否则不要把说明文字、箭头或水印放进成品画面。"
            "\n\n执行路由：用户只想讨论或完善设定时，先输出 Prompt；用户要求实际生成或修改画布时，"
            "在不需要继续提问的情况下请求 plan_canvas，并在计划中使用 mode=image 的 create_node 或选中图片节点的 update_node_config。"
            "新建节点的 prompt 必须包含完整正向 Prompt 和负面约束；不要只写“角色三视图”。"
            "计划获批后由服务端真正调用图片模型，返回结果会写入图片节点；模型未配置或生成失败时显示真实错误，不要声称成功。"
        ),
    },
)


def list_skills() -> list[dict[str, Any]]:
    return [dict(skill) for skill in SKILLS]


def get_skill(skill_id: str | None) -> dict[str, Any] | None:
    if not skill_id:
        return None
    return next((skill for skill in SKILLS if skill["id"] == skill_id), None)
