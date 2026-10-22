# macOS 企业微信密钥辅助脚本

> 主仓库不包含 `wechat/` 工具本体（本地单独维护）；这里只保留 macOS 侧辅助脚本。

这里保留 macOS 版企业微信数据库密钥提取的尝试脚本。**当前在 macOS 27 + 企业微信 5.0.12 上不可用**，保留是为了后续换环境或换版本时继续。

## 背景

macOS 企业微信 5.x 的 `Profiles/<hash>/Messages1/Info.db` 使用 wxSQLite3 风格的 AES-128-CBC 按页加密：

- 页大小 4096
- per-page key：`MD5(raw_key + pgno_LE_u32 + "sAlT")`
- raw key：16 字节，登录后存在于进程内存

`wechat/lib.py` 和 `wechat/decrypt.py` 的算法与它一致，缺的是 raw key。

## find_wecom_keys_macos.c

来源：`huangserva/wechat-radar` 的 `scripts/decrypt/decrypt/find_wecom_keys_macos.c`（文件头保留上游署名）。它只读目标进程内存、用数据库 page 1 校验候选 key，最后写一个 0600 的 JSON，不修改企业微信数据。

编译：

```bash
cc -O2 -Wall -Wextra -o find_wecom_keys_macos find_wecom_keys_macos.c
```

用法：

```bash
sudo ./find_wecom_keys_macos <pid> \
  ~/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/<hash>/Messages1 \
  ~/.config/wechat/wecom_keys.json
```

## 当前环境实测

- `task_for_pid failed: 5`：企业微信是 hardened runtime，sudo 也无法 attach。
- `lldb -p`：`Not allowed to attach`。
- DTrace：SIP 开启，`failed to grab pid`。
- `heap` / `leaks`：受限进程只能读只读段，拿不到可写堆内容。
- core dump：`kern.coredump=1`，但实测不产生 core。
- 企业微信官方 `chat` API：`errcode 853006`，企业未开通。

结论：在不关闭 SIP、不重签应用、不重启企业微信的前提下，拿不到 raw key。

## trace.d

用于在 `CC_MD5` / `CCCrypt` 入口抓 16 字节 key 的 DTrace 脚本：

```bash
sudo dtrace -p <pid> -s trace.d -o /tmp/wecom-trace.out
```

15 秒内打开一个聊天触发数据库解密。当前环境会被 SIP 拒绝，脚本保留备用。

## 安全

- `wecom_keys.json` 和 `~/.config/wechat/master_keys` 是敏感文件，权限保持 0600，不要提交。
- 解密后的 SQLite 包含完整聊天内容，也不要提交。
- 本目录不包含任何 key、解密数据库或编译产物。
