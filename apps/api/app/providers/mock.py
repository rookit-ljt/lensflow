from .base import GenerationRequest, GenerationResult


class MockVideoProvider:
    """No-credential provider that verifies orchestration without claiming a video exists."""

    name = "mock"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            provider_job_id=f"mock-{request.generation_id}",
            output_url=f"mock://generation/{request.generation_id}",
        )


class MockTextProvider:
    """Deterministic text provider used by tests and offline development."""

    name = "mock"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            provider_job_id=f"mock-text-{request.generation_id}",
            output_text=f"文本生成结果：{request.prompt}",
        )


class MockImageProvider:
    """Persists an image execution receipt without fabricating image bytes."""

    name = "mock"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            provider_job_id=f"mock-image-{request.generation_id}",
            output_url=f"mock://image/{request.generation_id}",
        )
