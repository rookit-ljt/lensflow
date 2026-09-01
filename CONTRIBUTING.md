# 贡献指南

感谢参与 LibTV。提交代码前，请先阅读 `README.md`、`SECURITY.md` 和 `outputs/` 下的架构文档。

## 本地开发

```bash
pnpm install
pnpm typecheck
pnpm build
pnpm api:setup
cd apps/api
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
```

复制 `.env.example` 为 `.env` 后再启动服务。不要提交 `.env`、数据库、上传媒体、构建目录或包含真实凭据的日志。

## 提交变更

1. 从最新主分支创建短生命周期分支。
2. 一个 Pull Request 聚焦一个可验证的变更，补充必要的测试和文档。
3. 前端变更应通过 typecheck 和 production build；API 变更应通过 Ruff 和 pytest。
4. 新增 Provider、Skill、模型映射或素材时，说明来源、许可证、服务条款和是否允许再分发。
5. 不要在测试中调用真实付费模型；优先使用 Mock Provider 或显式的集成测试配置。

## Pull Request 清单

- [ ] 没有提交密钥、个人数据、数据库或上传文件。
- [ ] 已补充或更新测试、README/架构文档。
- [ ] 已运行前端 typecheck/build 与 API lint/test。
- [ ] 已说明兼容性、迁移和回滚影响。
