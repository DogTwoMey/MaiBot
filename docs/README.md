# 文档索引

本目录混合 **fork 自维护** 和 **upstream 原生** 两类文档。为避免 upstream 合并冲突，fork 专属文档放在 [`fork/`](fork/) 子目录，私有/WIP 文档放在 [`private/`](private/) 子目录（可在 gitignore 排除），其余根下 `*.md` 都来自 upstream。

---

## Fork 专属文档（[`fork/`](fork/)）

| 文件 | 内容 |
|------|------|
| [`fork/deployment.md`](fork/deployment.md) | **工程层主文档**。部署 / 启停 / 配置 / 运维 / 故障排查。新机器从这里开始。 |
| [`fork/design_divergence.md`](fork/design_divergence.md) | **业务层主文档**。fork 相对 upstream 的长期代码分歧（path_utils、本地 dist、@ 保活、KV cache revert、孤儿 tool call 兜底等）。合并 upstream 前必读。 |

## 私有文档（[`private/`](private/)，submodule）

`private/` 是指向独立私库 [`DogTwoMey/PrivateDocuments`](https://github.com/DogTwoMey/PrivateDocuments) 的 git submodule，配置 `update = none` —— 路人 clone 时被自动跳过，不会影响他们；自己用时显式 `git submodule update --init docs/private --checkout` 拉取。

| 子目录 | 内容 |
|------|------|
| `private/reviews/` | 各次 upstream 合并的具体处理记录 / 预合并报告 / 冲突方案 |
| `private/personas/` | 角色人格定义本地定制备份 |
| `private/utils/` / `private/worldview/` | 其他个人/项目内部资料 |

## Upstream 原生文档

保留这些是为了 sync 上游时无冲突：

| 文件 | 内容 | 对 fork 的相关度 |
|------|------|-----|
| [`README_CN.md`](README_CN.md) / [`README_EN.md`](README_EN.md) | 项目介绍 | 高 |
| [`CONTRIBUTE.md`](CONTRIBUTE.md) | 上游贡献规范 | 中（向上游提 PR 时参考）|
| [`a_memorix_sync.md`](a_memorix_sync.md) | A_Memorix 长期记忆子系统契约 | 中 |
| [`i18n.md`](i18n.md) | i18n 机制说明 | 中 |
| [`minimal-cross-platform-plan.md`](minimal-cross-platform-plan.md) | 跨平台（非 QQ）运行时改造计划 | 低（当前只用 QQ）|
| [`crowdin_workflow_alignment_brief.md`](crowdin_workflow_alignment_brief.md) | upstream i18n CI 流程简报 | 低（fork 不跑 Crowdin）|
| [`github-actions-crowdin-workflow-report.md`](github-actions-crowdin-workflow-report.md) | 同上，侧重 GH Actions 实施报告 | 低 |

> upstream 文档不主动删除 —— 它们会随 `sync_upstream.py` 持续更新。若需裁剪以减少干扰，请只删本地副本，**不要**在本 fork 的 `main` 分支上 commit 删除（否则每次合并 upstream 都要重做冲突）。
