import json
from pathlib import Path

import httpx

from app.config import Settings
from app.providers.base import GenerationContext, GenerationRequest
from app.providers.local_h3_video import LocalH3VideoProvider
from app.schemas import GenerationCreate


def test_generation_schema_accepts_local_h3_provider() -> None:
    payload = GenerationCreate(provider="local_h3", kind="video", prompt="雪地红狐狸")

    assert payload.provider == "local_h3"


def test_local_h3_video_provider_submits_polls_and_returns_video_url() -> None:
    requests: list[httpx.Request] = []
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                202,
                json={
                    "id": "abc123def456",
                    "status": "queued",
                    "status_url": "/v1/jobs/abc123def456",
                },
            )
        poll_count += 1
        if poll_count == 1:
            return httpx.Response(200, json={"id": "abc123def456", "status": "running"})
        return httpx.Response(
            200,
            json={
                "id": "abc123def456",
                "status": "succeeded",
                "video_url": "/v1/jobs/abc123def456/video",
            },
        )

    settings = Settings(
        local_video_base_url="http://127.0.0.1:8787",
        local_video_request_timeout_seconds=30,
        local_video_poll_interval_seconds=0,
        _env_file=None,
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = LocalH3VideoProvider(settings, client=client, sleep=lambda _: None)

    result = provider.generate(
        GenerationRequest(
            generation_id="generation-123456789",
            shot_id="shot-1",
            title="海岸公路",
            prompt="一只红狐狸在雪地行走",
            duration_seconds=5,
            model="minimax-h3-local",
            parameters={
                "preset": "custom",
                "width": 256,
                "height": 256,
                "duration_seconds": 1,
                "steps": 4,
                "seed": 42,
                "camera_motion": "跟拍",
            },
            contexts=(
                GenerationContext(
                    node_id="text-1",
                    title="环境描述",
                    kind="text",
                    text="冬季松林，风雪很大",
                ),
            ),
        )
    )

    assert result.provider_job_id == "abc123def456"
    assert result.output_url == "http://127.0.0.1:8787/v1/jobs/abc123def456/video"
    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    body = json.loads(requests[0].content)
    assert body == {
        "prompt": (
            "参考文本 1（环境描述）：\n冬季松林，风雪很大\n\n"
            "请结合以上参考完成以下任务：\n一只红狐狸在雪地行走，镜头运动：跟拍"
        ),
        "preset": "custom",
        "seconds": 1.0,
        "steps": 4,
        "output_name": "libtv-generation-1",
        "width": 256,
        "height": 256,
        "seed": 42,
    }


def test_local_h3_video_provider_maps_selected_first_and_last_frames(tmp_path: Path) -> None:
    first_frame = tmp_path / "start.png"
    last_frame = tmp_path / "end.png"
    first_frame.write_bytes(b"start-frame")
    last_frame.write_bytes(b"end-frame")
    submitted: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            submitted.update(json.loads(request.content))
            return httpx.Response(
                202,
                json={"id": "frame-job", "status_url": "/v1/jobs/frame-job"},
            )
        return httpx.Response(
            200,
            json={"status": "succeeded", "video_url": "/v1/jobs/frame-job/video"},
        )

    settings = Settings(local_video_poll_interval_seconds=0, _env_file=None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = LocalH3VideoProvider(settings, client=client, sleep=lambda _: None)

    provider.generate(
        GenerationRequest(
            generation_id="generation-frames",
            shot_id="shot-1",
            title="首尾帧测试",
            prompt="人物自然转头，动作平滑",
            duration_seconds=2,
            parameters={
                "preset": "preview",
                "duration_seconds": 2,
                "steps": 4,
                "first_frame_node_id": "start-node",
                "last_frame_node_id": "end-node",
            },
            contexts=(
                GenerationContext(
                    node_id="end-node",
                    title="尾帧",
                    kind="image",
                    image_url=str(last_frame),
                ),
                GenerationContext(
                    node_id="start-node",
                    title="首帧",
                    kind="image",
                    image_url=str(first_frame),
                ),
            ),
        )
    )

    assert submitted["first_frame"] == str(first_frame)
    assert submitted["last_frame"] == str(last_frame)


def test_local_h3_video_provider_downloads_remote_frame_to_temporary_file() -> None:
    submitted_frame: Path | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submitted_frame
        if request.url.host == "assets.test":
            return httpx.Response(
                200,
                content=b"remote-frame",
                headers={"content-type": "image/png"},
            )
        if request.method == "POST":
            body = json.loads(request.content)
            submitted_frame = Path(body["first_frame"])
            assert submitted_frame.read_bytes() == b"remote-frame"
            return httpx.Response(
                202,
                json={"id": "remote-job", "status_url": "/v1/jobs/remote-job"},
            )
        return httpx.Response(
            200,
            json={"status": "succeeded", "video_url": "/v1/jobs/remote-job/video"},
        )

    settings = Settings(local_video_poll_interval_seconds=0, _env_file=None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = LocalH3VideoProvider(settings, client=client, sleep=lambda _: None)

    provider.generate(
        GenerationRequest(
            generation_id="generation-remote-frame",
            shot_id="shot-1",
            title="远程首帧测试",
            prompt="镜头缓慢推进",
            duration_seconds=2,
            parameters={"first_frame_node_id": "remote-start", "last_frame_node_id": ""},
            contexts=(
                GenerationContext(
                    node_id="remote-start",
                    title="首帧",
                    kind="image",
                    image_url="http://assets.test/start.png",
                ),
            ),
        )
    )

    assert submitted_frame is not None
    assert not submitted_frame.exists()


def test_local_h3_video_provider_maps_720p_without_custom_dimensions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["preset"] == "720p"
            assert "width" not in body
            assert "height" not in body
            return httpx.Response(
                202,
                json={"id": "abc123def456", "status_url": "/v1/jobs/abc123def456"},
            )
        return httpx.Response(
            200,
            json={"status": "succeeded", "video_url": "/v1/jobs/abc123def456/video"},
        )

    settings = Settings(local_video_poll_interval_seconds=0, _env_file=None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = LocalH3VideoProvider(settings, client=client, sleep=lambda _: None)

    provider.generate(
        GenerationRequest(
            generation_id="generation-1",
            shot_id="shot-1",
            title="海岸公路",
            prompt="海岸公路跟拍",
            duration_seconds=10,
            parameters={"preset": "720p", "duration_seconds": 10},
        )
    )


def test_local_h3_video_provider_does_not_infer_keyframes_from_image_contexts() -> None:
    submitted: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            submitted.update(json.loads(request.content))
            return httpx.Response(202, json={"id": "text-job", "status_url": "/v1/jobs/text-job"})
        return httpx.Response(200, json={"status": "succeeded", "video_url": "/video"})

    settings = Settings(local_video_poll_interval_seconds=0, _env_file=None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = LocalH3VideoProvider(settings, client=client, sleep=lambda _: None)

    provider.generate(GenerationRequest(
        generation_id="generation-text-only",
        shot_id="shot-1",
        title="纯文本",
        prompt="A slow tracking shot.",
        duration_seconds=1,
        parameters={"video_reference_mode": "text"},
        contexts=(GenerationContext(
            node_id="unused-image",
            title="未启用的图片",
            kind="image",
            image_url="/tmp/unused.png",
        ),),
    ))

    assert "first_frame" not in submitted
    assert "last_frame" not in submitted
    assert "reference_images" not in submitted


def test_local_h3_video_provider_maps_ordered_ref2va_images(tmp_path: Path) -> None:
    scene = tmp_path / "scene.png"
    character = tmp_path / "character.png"
    scene.write_bytes(b"scene")
    character.write_bytes(b"character")
    submitted: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            submitted.update(json.loads(request.content))
            return httpx.Response(202, json={"id": "ref-job", "status_url": "/v1/jobs/ref-job"})
        return httpx.Response(200, json={"status": "succeeded", "video_url": "/video"})

    settings = Settings(local_video_poll_interval_seconds=0, _env_file=None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = LocalH3VideoProvider(settings, client=client, sleep=lambda _: None)
    prompt = """subject_definitions:
<Subject 1> is a city from <Picture 1>.
summary:
[reference generation] Test.
retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - Test.
detailed_description:
[Shot 1] Test.
overall_soundscape:
Wind.
non_diegetic_music:
N/A"""

    provider.generate(GenerationRequest(
        generation_id="generation-ref2va",
        shot_id="shot-1",
        title="全参考",
        prompt=prompt,
        duration_seconds=1,
        parameters={
            "video_reference_mode": "ref2va",
            "reference_image_node_ids": ["scene", "character"],
        },
        contexts=(
            GenerationContext(node_id="character", title="角色", kind="image", image_url=str(character)),
            GenerationContext(node_id="scene", title="场景", kind="image", image_url=str(scene)),
        ),
    ))

    assert submitted["reference_images"] == [str(scene), str(character)]
    assert "first_frame" not in submitted
    assert "last_frame" not in submitted


def test_local_h3_video_provider_rejects_mixed_ref2va_and_keyframes(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    settings = Settings(local_video_poll_interval_seconds=0, _env_file=None)
    provider = LocalH3VideoProvider(settings, client=httpx.Client(), sleep=lambda _: None)
    prompt = """subject_definitions:
summary:
retention_analysis:
detailed_description:
overall_soundscape:
non_diegetic_music:"""

    try:
        provider.generate(GenerationRequest(
            generation_id="generation-invalid",
            shot_id="shot-1",
            title="非法混用",
            prompt=prompt,
            duration_seconds=1,
            parameters={
                "video_reference_mode": "ref2va",
                "reference_image_node_ids": ["image"],
                "first_frame_node_id": "image",
            },
            contexts=(GenerationContext(
                node_id="image", title="图片", kind="image", image_url=str(image),
            ),),
        ))
    except RuntimeError as exc:
        assert "不能同时使用首帧或尾帧" in str(exc)
    else:
        raise AssertionError("Expected mixed reference modes to be rejected")
