# 测试记录

本目录记录实际执行的验证结果。所有测试使用Python标准库`unittest`；本地无PostgreSQL/Redis时以SQLite内存库和假Redis替代，计算逻辑与数据库方言无关。

## 运行方式

```bash
cd backend
JWT_SECRET=test DATABASE_URL=sqlite:////tmp/t.db REDIS_URL=redis://127.0.0.1:1/0 \
  python -m unittest discover -s tests -v
```

## 2026-11-20 结果

命令同上，`Ran 19 tests ... OK`。

### `tests/test_allocation.py`（12项）
- 精确匹配的2×2实例目标为0，返回`[[1,5],[5,1]]`；等级按Unicode排序为`一级`、`特级`。
- 120个随机3×3实例与穷举对照：目标值与按产地、等级排序后的字典序解完全一致；无解判断一致（至少60个可行实例参与比较）。
- 并列实例中`[[1,1],[0,1]]`以相同L1胜过`[[0,2],[1,0]]`，确认字典序规则。
- 空格子份数恒为0。
- 缺产地类别、缺等级类别、两套总数不一致分别返回`target_without_samples`、`totals_mismatch`。
- 两轴各自可达但不可同时达标返回`support_disconnected`，并列出不平衡的支撑分组。
- 诊断函数不抛异常，可行时`feasible=True`。
- 同格样本平分权重：2份实收、1份分配得到每份权重1/2；权重合计等于目标总份数，累计分布收敛到1。
- 篡改权重合计后激活前核对抛错。
- 未加权分布与线性插值手算一致（4份样本中位数5.15）。

### `tests/test_calibration_lifecycle.py`（7项）
- 最新申请完成后生效。
- 较新申请排队时，较早的queued/running申请标记superseded；先算完较早者也不能生效。
- 较新申请先算完，再处理较早申请，生效版本仍是较新者。
- 模拟较早申请在较新申请落库后才出队（强制改回queued），处理后被标记superseded。
- 无解申请不改变生效版本，诊断码为`target_without_samples`。
- 冻结结果的权重被破坏时，激活前核对失败、申请failed、旧版保持生效。
- 在较新版本生效后再次提交，最新申请重新成为生效版本。

### 手工API冒烟（TestClient + 合成种子）
- 登录、读取批次与观测均成功；观测返回`origin`、`grade`。
- `/calibrations` 列表不返回快照与结果；`/calibrations/{id}` 返回快照。
- POST `/calibrations` 返回queued；`process` 后completed且生效，目标12份、实收108份时绝对差之和为108，两轴逐项达标。
- GET `/calibrations/active` 返回生效编号；PUT 观测的`label` 返回200。
- 未知产地目标返回422“未知产地：火星”；观察员创建返回403。
- 断连实例（东岭只收特级、南坡只收一级；产地各5份，等级目标3/7份）返回`infeasible`：`individually_reachable=true`、`simultaneous_feasible=false`，blocking列出两个不平衡支撑组，且不激活。

## 未在本环境验证
- 真实PostgreSQL行锁与Redis队列：本机无docker，使用SQLite和假Redis。并发语义由`Study`行锁加申请编号比较实现，测试覆盖编号比较分支。
- 浏览器端页面渲染：仅做ES模块语法检查，未在浏览器中点击验证。
