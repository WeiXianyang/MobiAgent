# 任务2 用户多模态数据管理与画像生成阶段报告

## 输入数据

本阶段只读消费任务1已有成功 run 和 daily-log，没有重新运行手机 workflow。

- 20260524-205318-basic-gui-task: app=微信, package=com.tencent.mm, summary=C:\Users\wxy\Desktop\科研考核任务\MobiAgent\runner\mobiagent\workflow\test-runs\20260524-205318-basic-gui-task\run_summary.json, daily_logs=2, screenshots=15
- 20260524-231720-basic-gui-task-xiaohongshu-goal-v4: app=小红书, package=com.xingin.xhs, summary=C:\Users\wxy\Desktop\科研考核任务\MobiAgent\runner\mobiagent\workflow\test-runs\20260524-231720-basic-gui-task-xiaohongshu-goal-v4\run_summary.json, daily_logs=3, screenshots=6
- 20260525-011614-basic-gui-task-meituan-goal-v7: app=美团, package=com.sankuai.meituan, summary=C:\Users\wxy\Desktop\科研考核任务\MobiAgent\runner\mobiagent\workflow\test-runs\20260525-011614-basic-gui-task-meituan-goal-v7\run_summary.json, daily_logs=7, screenshots=2
- 20260525-024026-basic-gui-task-taobao-goal-v9: app=淘宝, package=com.taobao.taobao, summary=C:\Users\wxy\Desktop\科研考核任务\MobiAgent\runner\mobiagent\workflow\test-runs\20260525-024026-basic-gui-task-taobao-goal-v9\run_summary.json, daily_logs=8, screenshots=3

## 抽取规则

- 淘宝足迹映射为 `shopping_browse`，只记录商品品类、店铺/品牌信号和价格信号，标记为候选偏好。
- 美团订单映射为 `order_record`，记录商户/服务、价格、订单状态和服务类型；已完成订单不生成待支付事项。
- 小红书浏览记录映射为 `content_history_state`，空记录只证明无法推断内容兴趣。
- 微信聊天映射为 `chat_context`，只保留 VLM 摘要级上下文，不保存或扩散原始聊天文本。

## 事件统计

- chat_context: 10
- content_history_state: 1
- order_record: 1
- shopping_browse: 1

## 关系统计

- after: 9
- before: 9
- behavior_causal: 1
- same_day: 56
- spatial: 1

## 用户画像

- [沟通/社交线索] 微信聊天保留10条摘要级社交上下文，不扩散原始聊天文本。 证据=evt_054f45dfee,evt_bfb6faa2db,evt_02a4f3fb05,evt_2e1ecf4ae7,evt_9b343bc458,evt_24c64970bb,evt_41876e76ea,evt_1d61ace426,evt_18ca147de5,evt_85a4e04884 置信度=0.68
- [内容兴趣] 小红书浏览记录页面为空，当前不能据此推断内容兴趣。 证据=evt_df0c196d14 置信度=0.8
- [生活服务/消费习惯] 存在骑行,外卖消费记录；订单状态信号为已完成,已完成,已完成。 证据=evt_f0919096fd 置信度=0.82
- [购物偏好] 候选购物偏好：近期浏览过建材,护肤品；价格信号为¥3.02,¥13.4。 证据=evt_a615c4ef78 置信度=0.78

## 待办事项

- 复查近期购物需求并进行比价: 淘宝足迹只证明近期浏览，适合生成弱提醒而不是长期偏好结论。 status=candidate priority=low

## 检索示例

- `最近购物偏好` -> profile:profile_2e2f381840 score=6; todo:todo_4c0979fa6b score=5; event:evt_1d61ace426 score=2
- `用户有哪些待办` -> todo:todo_4c0979fa6b score=2; event:evt_054f45dfee score=1; event:evt_85a4e04884 score=1
- `美团订单反映了什么消费习惯` -> profile:profile_08a228c88f score=6; event:evt_f0919096fd score=4; event:evt_9b343bc458 score=2

## 验证命令

- `python -m unittest runner.mobiagent.profile_pipeline.test_profile_pipeline` -> 单元测试覆盖采集、抽取、关系、画像、待办、检索与报告结构。
- `python -m runner.mobiagent.profile_pipeline.cli build-profile` -> 生成事件、关系、画像、待办和检索索引。
- `python -m runner.mobiagent.profile_pipeline.cli search --query "最近购物偏好"` -> 命中购物画像和候选待办。
- `python -m runner.mobiagent.profile_pipeline.cli search --query "用户有哪些待办"` -> 命中候选待办。
- `python -m runner.mobiagent.profile_pipeline.cli search --query "美团订单反映了什么消费习惯"` -> 命中生活服务/消费习惯画像和美团订单事件。

## 输出文件

- `C:\Users\wxy\Desktop\科研考核任务\MobiAgent\runner\mobiagent\profile_pipeline\artifacts\events.jsonl`
- `C:\Users\wxy\Desktop\科研考核任务\MobiAgent\runner\mobiagent\profile_pipeline\artifacts\relations.jsonl`
- `C:\Users\wxy\Desktop\科研考核任务\MobiAgent\runner\mobiagent\profile_pipeline\artifacts\profile.json`
- `C:\Users\wxy\Desktop\科研考核任务\MobiAgent\runner\mobiagent\profile_pipeline\artifacts\todos.json`
- `C:\Users\wxy\Desktop\科研考核任务\MobiAgent\runner\mobiagent\profile_pipeline\artifacts\search_index.json`

## 局限性与任务3衔接

当前闭环依赖任务1 VLM 结构化输出和截图路径，未额外调用外部 Mem0/Milvus 服务，因此可离线复现。画像均为候选画像或摘要级线索，可作为任务3主动补全、弱提醒、周期性报告生成的输入，但不应作为稳定长期偏好或敏感属性判断。
