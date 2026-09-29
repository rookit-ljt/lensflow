from app.agent_skills import get_skill, list_skills


def test_character_turnaround_skill_is_curated_and_triggerable():
    skill = get_skill("character-turnaround-prompts")
    assert skill is not None
    assert skill["slug"] == "/character-turnaround-prompts"
    assert "三视图" in skill["description"]
    assert {"角色设定", "正侧背", "一致性"}.issubset(skill["tags"])
    instruction = skill["instruction"]
    for phrase in (
        "请求创建新的图片生成节点",
        "左侧正面视图、中间侧面视图、右侧背面视图",
        "正向 Prompt",
        "负面 Prompt",
        "平台适配",
        "consistent costume",
        "mode=image",
        "plan_canvas",
    ):
        assert phrase in instruction


def test_skill_catalog_contains_unique_ids_and_slugs():
    skills = list_skills()
    assert len({skill["id"] for skill in skills}) == len(skills)
    assert len({skill["slug"] for skill in skills}) == len(skills)
