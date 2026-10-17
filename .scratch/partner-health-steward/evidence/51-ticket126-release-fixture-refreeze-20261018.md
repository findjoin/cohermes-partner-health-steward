# Ticket126 external DynamoDB fixture有界返冻结

Reviewed checkpoint `1158d51d100bbf45339414059e6c358a29d549a4` / tree `bd8cb08c42812ba60802bac15fdb1c6220f43d60`。仅126 verifier与合同appendix修正123 client_factory外部边界对真实release摘要的支持；全部五项测试方法AST与R3完全相同、设计与旧122/123文件不变。R3 unknown ACK权威继续保留；具体false-red原因及新fixture语义见合同最后一节。

root独立运行 `python3 -I -B /tmp/ticket126-r4-fixture-characterization.py`，输出 `/tmp/ticket126-r4-root-characterization.log`：实际Core/Plugin/生产Dynamo释放链accepted，真实SHA原样保存；同owner只读重放、异owner HeadConflict，六类条件原子拒绝。另独立核对五方法AST、compile/diff。新最高五门与full794尚未运行；局部proof不是整票完成。

## Spec

**PASS — bounded R4 Spec-axis review.** No P0–P2 causal findings in this fixture correction or contract appendix.

- Commit: `1158d51d100bbf45339414059e6c358a29d549a4`
- Tree: `bd8cb08c42812ba60802bac15fdb1c6220f43d60`
- Clean checkout; both specified blobs match.

Read-only, in-memory checks confirmed exact SHA preservation, removal of only the target active effect, and atomic rejection for wrong lease, holder, released state, operation owner, missing active effect, and wrong deletion. Nonrelease transactions delegate to the original fake. All five acceptance-method ASTs match the parent; compile and diff checks pass.

This is **pre-formal verifier refreeze**, solely the Spec-axis result—not dual-axis approval, root freeze, product completion, or real AWS/Weixin/deployment acceptance. New formal five-gate/full794 results remain unclaimed; five gates alone do not prove sufficiency.

## Standards

**PASS — Standards 轴，有界 R4 夹具修正审查。**

- Commit：`1158d51d100bbf45339414059e6c358a29d549a4`
- Tree：`bd8cb08c42812ba60802bac15fdb1c6220f43d60`
- 合同／测试 blob 与指定值一致，工作区干净。

仅审查两文件差异及直接 122/123 fake 上下文，未发现可复现的 P0–P2 因果问题。修正使用既有 `client_factory` 外部边界；非 release 委托原 fake。释放前检查租约、holder、未释放状态、精确 operation ownership 及 active effect，全部通过后才保存原始 SHA 摘要并删除对应活动租约。没有生产补丁或授权、report、handoff 替身。

独立确认相对父提交的五个测试方法 AST 完全不变，内存编译及 diff 检查通过。合同保留旧正式失败结果，并明确新五门／794 尚未执行；五门数量不构成充分性证明。

这是 **pre-formal verifier refreeze 的 Standards PASS**，不代表双轴已完成、root 已冻结、产品完成或真实 AWS／微信／部署验收。未调用服务、修改文件或读取真实配置、凭据、健康数据。

## Root authority

同一最新checkpoint双PASS，允许正式执行修正夹具后的原样五门／当前794全量。唯一设计blob `4a6ec81c94edab252936815cf0fc98925def3d0f` 不变；最新独立合同blob `6bbc200afaa676fd42c8b76f68a3b7c422fdd89b`，verifier blob `df3427c9add51fe82456adf99f33ba7b9adfa272` 取代Evidence50旧对应两项。新fixture不放宽生产Provider、Core终态或unknown权限；实际产品接线、未知cursor及旧124兼容仍必须以正式门验证。没有真实AWS/模型/微信/部署或主人验收声明。
