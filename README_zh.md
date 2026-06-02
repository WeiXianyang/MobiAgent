<div align="center">
  <picture>
    <img alt="MobiAgent" src="assets/logo.png" width=10%>
  </picture>
</div>

<h3 align="center">
MobiAgent: A Systematic Framework for Customizable Mobile Agents
</h3>

<p align="center">
| <a href="https://arxiv.org/abs/2509.00531"><b>MobiAgent论文</b></a> | <a href="https://arxiv.org/abs/2512.15784"><b>MobiMem论文</b></a> | <a href="https://huggingface.co/collections/IPADS-SAI/mobimind-68b2aad150ccafd9d9e10e4d"><b>Huggingface</b></a> | <a href="https://github.com/IPADS-SAI/MobiAgent/releases/tag/v1.0.1"><b>App</b></a> |
</p> 

<p align="center">
 <a href="README.md">English</a> | <strong>中文</strong>
</p> 

---

## 简介

**MobiAgent**是一个强大的、可定制的移动端智能体系统，包含：

* **智能体模型家族：** MobiMind
* **智能体加速框架：** AgentRR
* **智能体评测基准：** MobiFlow

**系统架构**:

<div align="center">
<p align="center">
  <img src="assets/arch_zh.png" width="100%"/>
</p>
</div>

## 新闻

- [2026.3.14] 🔥 我们发布了首个能够GUI操控手机的小龙虾 [MobiClaw](https://github.com/IPADS-SAI/MobiClaw) 和端到端GUI模型[MobiMind-1.5-4B](https://www.modelscope.cn/models/fengerhu1/MobiMind-1.5-4B-0313)。
- [2025.12.26] 📱 **支持手机端纯本地推理！** 详见 [`phone_runner/README.md`](phone_runner/README.md)。
- [2025.12.25] 🛠️ 我们发布了**统一GUIAgent执行框架**，支持一键配置运行各GUIAgent模型（Mobiagent、UI-TARS、AutoGLM、Qwen-VL、Gemini等）。详见[Unify Runner README](https://github.com/IPADS-SAI/MobiAgent/blob/unify-runner/runner/RUNNER_README.md)。
- [2025.12.08] 我们发布了 [MobiMind-Reasoning-4B](https://huggingface.co/IPADS-SAI/MobiMind-Reasoning-4B-1208) 及其量化版本 [MobiMind-Reasoning-4B-AWQ](https://huggingface.co/IPADS-SAI/MobiMind-Reasoning-4B-1208-AWQ)。
- [2025.11.03] 新增多任务执行支持。详见 [多任务 README](runner/mobiagent/multi_task/README.md)。
- [2025.11.03] 引入用户画像记忆系统，通过`--user_profile on`启用。详见 [用户画像 README](runner/README.md#用户画像与偏好记忆)。

<details><summary>完整新闻</summary>
<ul>
  <li>[2025.10.31] 我们更新了基于 Qwen3-VL-4B-Instruct 的 MobiMind-Mixed 模型！下载地址：<a href="https://huggingface.co/IPADS-SAI/MobiMind-Mixed-4B-1031">MobiMind-Mixed-4B-1031</a>。</li>
  <li>[2025.9.30] 新增经验记忆模块。</li>
  <li>[2025.9.29] 我们开源了 MobiMind 混合版本，可同时胜任 Decider 和 Grounder 任务！下载地址：<a href="https://huggingface.co/IPADS-SAI/MobiMind-Mixed-7B">MobiMind-Mixed-7B</a>。</li>
</ul>
</details>

- [2025.8.30] 我们开源了 MobiAgent！

## 评测结果

<div align="center">
<p align="center">
  <img src="assets/result1.png" width="30%" style="margin-right: 15px;"/>
  <img src="assets/result2.png" width="30%" style="margin-right: 15px;"/>
  <img src="assets/result3.png" width="30%"/>
</p>
</div>

<div align="center">
<p align="center">
  <img src="assets/result_agentrr.png" width="60%"/>
</p>
</div>

## 演示

**移动端应用演示**:
<div align="center">
  <video src="https://github.com/user-attachments/assets/ab748578-7d17-47e1-a47c-4d9c3d34b28f"/>
</div>

**AgentRR 演示** (左：首次任务；右：后续任务)
<div align="center">
  <video src="https://github.com/user-attachments/assets/ef5268a2-2e9c-489c-b8a7-828f00ec3ed1"/>
</div>

**多任务演示**

任务：`在小红书查找2025年性价比最高的单反相机推荐，然后在淘宝搜索该相机，并将淘宝中的相机品牌、名称和价格通过微信发送给小赵。`
<div align="center">
  <video src="https://github.com/user-attachments/assets/92fdf23c-71d6-4c67-b02a-c3fa13fcc0e7"/>
</div>

## 项目结构

- `agent_rr/` - Agent Record & Replay框架
- `collect/` - 数据收集、标注、处理与导出工具
- `runner/` - 智能体执行器，通过ADB连接手机、执行任务、并记录执行轨迹
- `MobiFlow/` - 基于里程碑DAG的智能体评测基准
- `app/` - MobiAgent安卓App
- `deployment/` - MobiAgent移动端应用的服务部署方式

## 快速开始

### 通过 MobiAgent APP 使用

如果您想直接通过我们的 APP 体验 MobiAgent，请通过 [下载链接](https://github.com/IPADS-SAI/MobiAgent/releases/tag/v1.0.1) 进行下载，祝您使用愉快！

### 使用 Python 脚本

如果您想通过 Python 脚本来使用 MobiAgent，并借助Android Debug Bridge (ADB) 来控制您的手机，请遵循以下步骤进行：

#### 1. 环境配置

创建虚拟环境，例如，使用conda：

```bash
conda create -n MobiMind python=3.10
conda activate MobiMind
```

最简环境（如果您只想运行agent runner）：

```bash
# 安装最简化依赖
pip install -r requirements_simple.txt
```

完整环境（如果您想运行完整流水线）：

```bash
pip install -r requirements.txt

# 下载OmniParser模型权重
for f in icon_detect/{train_args.yaml,model.pt,model.yaml} ; do huggingface-cli download microsoft/OmniParser-v2.0 "$f" --local-dir weights; done

# 下载embedding模型
huggingface-cli download BAAI/bge-small-zh --local-dir ./utils/experience/BAAI/bge-small-zh

# Install OCR utils (可选)
sudo apt install tesseract-ocr tesseract-ocr-chi-sim

# 如果需要使用gpu加速ocr，需要根据cuda版本，手动安装paddlepaddle-gpu
# 详情参考 https://www.paddlepaddle.org.cn/install/quick，例如cuda 11.8版本：
python -m pip install paddlepaddle-gpu>=3.1.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/

```

#### 2. 手机配置

- 在Android设备上下载并安装 [ADBKeyboard](https://github.com/senzhk/ADBKeyBoard/blob/master/ADBKeyboard.apk)
- 在Android设备上，开启开发者选项，并允许USB调试
- 使用USB数据线连接手机和电脑

#### 3. 模型部署

下载好模型检查点后，使用 vLLM 部署模型推理服务：

download 地址：
- MobiMind-1.5-4B:
  -  [huggingface](https://huggingface.co/IPADS-SAI/MobiMind-1.5-4B-0313)
  -  [modelscope](https://www.modelscope.cn/models/fengerhu1/MobiMind-1.5-4B-0313)


```bash
vllm serve MobiMind-Reasoning-4B --port <decider/grounder port>
vllm serve Qwen/Qwen3-4B-Instruct --port <planner port>
```


#### 4. Agent 记忆系统设置（可选）

MobiAgent 支持三种类型的记忆系统以提升智能体性能：

##### 4.1 用户画像记忆

用户偏好记忆系统（Mem0）为规划阶段提供个性化上下文。要启用它，需要先设置后端存储：

Milvus（向量数据库）- 向量检索必需：

```bash
# 下载安装脚本
curl -sfL https://raw.githubusercontent.com/milvus-io/milvus/master/scripts/standalone_embed.sh -o standalone_embed.sh
# 启动 Docker 容器
bash standalone_embed.sh start
```

在 `.env` 文件中添加：
```bash
MILVUS_URL=http://localhost:19530
EMBEDDING_MODEL=/absolute/path/to/local/embedding/model
EMBEDDING_MODEL_DIMS=512
MEM0_COLLECTION_NAME=mobiagent_local
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=your_llm_endpoint_here
```

本地部署的最小示例如下：

```bash
# 1. 先启动 Milvus
bash profile-mem/standalone_embed.sh start

# 2. 启动本地 OpenAI 兼容 LLM 服务，供 Mem0 使用
bash profile-mem/manage_openai_llm_service.sh start

# 3. 在 runner/mobiagent/.env 中使用本地 embedding 模型和本地 LLM 端点
MILVUS_URL=http://127.0.0.1:19530
EMBEDDING_MODEL=/home/yourname/MobiAgent/profile-mem/models/embeddings/BAAI/bge-small-zh
EMBEDDING_MODEL_DIMS=512
MEM0_COLLECTION_NAME=mobiagent_local
OPENAI_API_KEY=local-openai-key
OPENAI_BASE_URL=http://127.0.0.1:18001/v1
MOBIAGENT_API_KEY=mobiagent-key
```

说明：
- `EMBEDDING_MODEL` 可以直接填写本地模型目录。在本仓库中，验证脚本会把 `BAAI/bge-small-zh` 下载到 `profile-mem/models/embeddings/BAAI/bge-small-zh`。
- `EMBEDDING_MODEL_DIMS` 必须与本地 embedding 模型的真实维度一致。当前这套本地下载的 `BAAI/bge-small-zh` 在本环境中的维度是 `512`。
- 如果你已有旧的 Milvus collection 且向量维度不同，建议通过 `MEM0_COLLECTION_NAME` 使用新的 collection 名称。
- 本地 LLM 服务可以用 `bash profile-mem/manage_openai_llm_service.sh start|stop|status` 管理。
- 可以用 `/home/reck/Utils/anaconda3/envs/MobiMind/bin/python profile-mem/verify_mem0_pipeline.py` 验证整套本地链路。

Neo4j（GraphRAG）- 图检索可选：

```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/testpassword \
  neo4j:5.23.0
```

在 `.env` 文件中添加：
```bash
NEO4J_URL=neo4j://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=testpassword
```

详细配置说明见 [runner README](runner/README.md#用户画像与偏好记忆)。

## Proactive Personal Memory

本项目新增 `runner/mobiagent/personal_memory` 作为 **PML-Hybrid** 轻量个人记忆系统。它以本地 SQLite 事件时间线为主体，优先支持时间范围、App、事件类型、任务状态、证据链和关系图检索；画像、待办和周报以 memory card 的方式压缩保存，供主动服务快速读取。

VectorDB 或 Mem0/Milvus 作为可选的标量+向量+多模态召回执行层，用于模糊表达、相似历史任务和弱匹配场景；精确查询、范围查询、因果关系、待办状态和证据链由 PML 的结构化索引和关系图承担。

Milvus 的使用边界：

- 标量标签负责时间、App、事件类型、任务、状态、隐私等级等范围过滤。
- 本地关系/卡片索引支持 “继续上次任务” “找未完成酒店预订线索” 等 Agent Search 步骤。
- 多模态证据层把 screenshot、UI tree、OCR、action trace、JSON evidence 绑定到记忆行。
- 渐进式披露层级记录每个成本层打开哪些字段：标量标签、摘要/卡片、关系上下文、证据引用、可选向量召回、原始证据。
- budget-aware embedding 策略默认先走结构化检索，只有候选不足时才调用向量后端；Milvus 可以承载缓存或预计算向量。

生命周期感知能力：

- **生命周期感知记忆**：根据更新时间进行置信度衰减，并根据相关画像和冲突检测调整画像优先级。
- **冲突画像检测**：识别偏好冲突，例如“喜欢火锅”和“最近避免辛辣”。
- **过期待办降权**：过期但仍打开的 todo 会自动降低主动服务优先级。
- **可解释检索路径**：每个 hit 返回 `explanation_trace`，说明查询计划、结构化过滤、文本匹配、关系链接、生命周期调分和最终分数来源。
- **Hybrid Agent Search plan**：`runner/mobiagent/personal_memory/hybrid.py` 会输出一次查询的标量过滤、FTS、关系/卡片、多模态证据、可选向量召回和重排阶段。
- **渐进式披露计划**：`HybridSearchPlan.disclosure_layers` 输出 L0-L5 成本边界，结构化/卡片/证据引用已经足够时，Agent Search 可以停止在向量召回或原始证据读取之前。

轻量化存储结构：

- `events` 是主事件时间线；`raw_artifacts` 只保存证据引用，避免把截图或 OCR 大块内容重复塞进主检索表。
- `memory_cards` 保存压缩后的画像、待办和周报卡片，供主动服务快速读取。
- `card_events` 和 `relation_events` 是轻量链接索引表，时间、App、任务、隐私级别等过滤可以走 SQL join，不需要扫描 JSON 数组。
- `events_fts`、`cards_fts` 和 `relations_fts` 提供本地全文检索；关系 FTS 会对短中文关系描述做子串扩展，保持原始 relation 行不变。
- `schema_meta` 记录存储格式版本，结构变化时只重建派生索引，不需要引入外部数据库迁移服务。
- `AgentMemoryQuery.include_explanation=False` 可关闭 `explanation_trace` 构造，用于生产或 benchmark 的低延迟检索路径。

渐进式披露层级：

| 层级 | 打开条件 | 内容 |
| --- | --- | --- |
| L0 | 总是打开 | 时间、App、事件类型、任务、状态、隐私标签 |
| L1 | 有文本查询或需要卡片检索 | 事件摘要、实体文本、卡片标题/正文 |
| L2 | 查询需要关系或卡片 | 关系边、卡片-事件链接、关系-事件链接 |
| L3 | 已有候选结果 | screenshot、UI tree、OCR、action trace、JSON 证据引用 |
| L4 | 结构化候选数低于阈值 | Milvus 或其他标量+向量召回 |
| L5 | agent 主动要求证据或 trace 置信度低 | 原始截图、完整 OCR、完整 UI tree、完整动作日志 |

核心命令：

```powershell
python -m runner.mobiagent.personal_memory.cli build --db memory.db --events events.json --artifacts artifacts.json --relations relations.json --profiles profile.json --todos todos.json
python -m runner.mobiagent.profile_pipeline.cli build-personal-memory --events-json events.jsonl --relations-json relations.jsonl --profiles-json profile.json --todos-json todos.json --db memory.db
python -m runner.mobiagent.personal_memory.cli search --db memory.db --query "生成过去一周画像报告"
python -m runner.mobiagent.personal_memory.cli plan --query "继续上次那个携程酒店任务"
python -m runner.mobiagent.personal_memory.benchmark_storage --db .tmp\personal_memory_benchmark.db --events 1000 --cards 200 --relations 200
```

##### 4.2 经验记忆

经验记忆使规划器能够检索并使用类似的过往任务执行经验。启动 Agent 执行器时添加 `--use_experience` 参数即可启用。

##### 4.3 动作记忆

动作记忆（AgentRR）缓存并复用成功的动作序列以加速任务执行。关于 ActTree 的复现与评测，见 [AgentRR README (ActTree)](agent_rr/README.md)。ActChain（基于经验的动作记忆）正在作为实验特性集成到 Agent Runner 中，见 [#49](https://github.com/IPADS-SAI/MobiAgent/pull/49)。

#### 5. 启动Agent执行器

在 `runner/mobiagent/task.json` 中写入想要测试的任务列表，然后启动Agent执行器

**基础启动**：
```bash
python -m runner.mobiagent.mobiagent \
  --service_ip <服务IP> \
  --decider_port <Decider模型端口> \
  --planner_port <Planner模型端口>
  # grounder_port在MobiMind-1.5-4B-0313之后不再使用
```

**启用用户画像记忆**：
```bash
python -m runner.mobiagent.mobiagent \
  --service_ip <服务IP> \
  --decider_port <Decider模型端口> \
  --planner_port <Planner模型端口> \
  --user_profile on \
  --use_graphrag off  # 使用 'on' 启用 GraphRAG (Neo4j)，'off' 使用向量检索 (Milvus)
  # grounder_port在MobiMind-1.5-4B-0313之后不再使用

```

常用参数：

- `--service_ip`：服务IP（默认：`localhost`）
- `--decider_port`：决策服务端口（默认：`8000`）
- `--grounder_port`：定位服务端口（默认：`8001`）
- `--planner_port`：规划服务端口（默认：`8002`）
- `--e2e`：端到端推理模式，减少grounder调用（默认：`True`）
- `--device`：设备类型，`Android` 或 `Harmony`（默认：`Android`）
- `--user_profile`：启用用户画像记忆，`on` 或 `off`（默认：`off`）
- `--use_graphrag`：使用 GraphRAG (Neo4j) 进行检索，`on` 或 `off`（默认：`off`）
- `--use_experience`：启用基于经验的任务改写（默认：`False`）
- `--data_dir <path>`：结果数据保存目录，默认为`runner/mobiagent`目录下的 `data/`
- `--task_file <path>`：任务列表文件路径，默认为`runner/mobiagent`目录下的 `task.json`

执行器启动后，将会自动控制手机并调用Agent模型，完成列表中指定的任务。

**重要提示**：如果您部署的是 MobiMind-Reasoning-4B 模型，请将 decider/grounder 端口都设置为统一个端口 `<decider/grounder port>`。

所有可用参数说明见 [runner README](runner/README.md#项目启动)。

**多任务执行**：

对于需要与多个应用交互的复杂任务，使用多任务执行器：

```bash
python -m runner.mobiagent.multi_task.mobiagent_refactored \
  --service_ip <服务IP> \
  --decider_port <Decider模型端口> \
  --grounder_port <Grounder模型端口> \
  --planner_port <Planner模型端口> \
  --task "您的多步骤任务描述"
```

有关详细的配置、多截图支持、OCR设置和经验记忆集成，请查看 [多任务README](runner/mobiagent/multi_task/README.md)。

## 子模块详细使用方式

详细使用方式见各子模块目录下的 `README.md` 文件。

## 引用

如果您在研究中使用了 MobiAgent，欢迎引用我们的[论文](https://arxiv.org/abs/2509.00531)：

```
@misc{zhang2025mobiagentsystematicframeworkcustomizable,
  title={MobiAgent: A Systematic Framework for Customizable Mobile Agents}, 
  author={Cheng Zhang and Erhu Feng and Xi Zhao and Yisheng Zhao and Wangbo Gong and Jiahui Sun and Dong Du and Zhichao Hua and Yubin Xia and Haibo Chen},
  year={2025},
  eprint={2509.00531},
  archivePrefix={arXiv},
  primaryClass={cs.MA},
  url={https://arxiv.org/abs/2509.00531}, 
}
@misc{liu2025trainingenablingselfevolutionagents,
  title={Beyond Training: Enabling Self-Evolution of Agents with MOBIMEM}, 
  author={Zibin Liu and Cheng Zhang and Xi Zhao and Yunfei Feng and Bingyu Bai and Dahu Feng and Erhu Feng and Yubin Xia and Haibo Chen},
  year={2025},
  eprint={2512.15784},
  archivePrefix={arXiv},
  primaryClass={cs.AI},
  url={https://arxiv.org/abs/2512.15784}, 
}
```

## 致谢
我们感谢MobileAgent，UI-TARS，Qwen-VL等优秀的开源工作，同时，感谢国家高端智能化家用电器创新中心对项目的支持。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=IPADS-SAI/MobiAgent&type=Date)](https://www.star-history.com/#IPADS-SAI/MobiAgent&Date)
