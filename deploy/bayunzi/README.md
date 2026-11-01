# bayunzi.shop 自动更新

仓库 `bayunyouzi/sub2api2` 的 `main` 分支通过 CI 和安全扫描后，GitHub Actions 构建 x86_64 镜像，并用一个临时 PostgreSQL、Redis 验证启动、登录页面和 API 认证。成功的部署包发布为 `deploy-main-完整提交SHA` 预发布版本，附有镜像标识、源码提交和 SHA-256。

服务器每五分钟查询 `main`，只部署与当前提交完全对应的成功构建。构建在 GitHub 运行，服务器通过公开下载地址获取程序包，无需把 SSH 密码、部署私钥、数据库凭据或 GitHub Token 存入仓库。程序包不包含业务数据和生产配置。

## 平时怎样更新

1. 将代码提交到 `main`，或把功能分支合并到 `main`。
2. 在仓库 Actions 查看 `CI`、`Security Scan` 和 `Publish main deployment`。
3. 构建发布成功后，等待服务器下一次检查。测试与构建所花的时间另计。

如果要更新上游开源项目，需要先把上游更新同步到这个仓库；上游仓库发生变化不会直接触发这台服务器更新。同步时保留 `.github/workflows/bayunzi-deploy.yml`、本目录和 CI 中的控制器测试。

## 更新期间的行为

- 保留现有 Compose 的数据目录、账号、JWT、固定 `TOTP_ENCRYPTION_KEY`、Nginx、Logo、域名和证书配置。
- PostgreSQL、Redis 的程序版本不随 sub2api 自动升级。
- 正式切换前，先在无法访问互联网的独立 Docker 网络中恢复数据库副本，试运行新版迁移及启动检查。此时正式服务继续运行，测试副本不能调用上游渠道。
- 切换时短暂停止应用，暂停接收新请求，保存数据库、Redis RDB、应用文件和旧 Compose；长时间进行中的调用可能被中断。
- 新版启动检查通过后恢复访问。如果正式启动失败，在恢复公开访问前还原刚才的快照及旧镜像。恢复失败会保留维护状态并暂停自动更新。
- 已经成功上线并接收新写入后，回退旧版本需要重新评估数据库兼容性；不要直接恢复旧快照覆盖新增数据。
- 最近三次完整部署快照和对应旧镜像保留在服务器。每日备份继续独立运行。自动更新不提供异地备份。

## 服务器操作

```bash
# 查询运行状态、日志和已部署提交
systemctl status sub2api-autodeploy.timer
journalctl -u sub2api-autodeploy.service -n 60 --no-pager
cat /opt/zeabur-migration/autodeploy/state.json

# 只检查是否有可部署版本，不执行更新
python3 /opt/zeabur-migration/autodeploy/autodeploy.py --check

# 立即检查并自动部署通过检查的新版本
systemctl start sub2api-autodeploy.service

# 暂停后续更新；不会中途打断已开始的部署
touch /opt/zeabur-migration/autodeploy/PAUSED

# 确认故障修复后恢复检查
rm -f /opt/zeabur-migration/autodeploy/PAUSED
```

同一提交失败后不会反复尝试；修复并推送新提交后重新检查。恢复流程异常时需要先检查私有的 `commands.log`、`transaction.json` 和快照，再由管理员执行 `autodeploy.py --recover`。维护标记位于 `/var/www/zeabur-public/sub2api-maintenance`；有未恢复的事务时不要手动删除它。

首次安装由管理员在原迁移目录中运行 `install.py`，核验维护规则、控制器测试、数据库副本升级与备份后，将私有 `autodeploy/config.json` 的 `enabled` 设置为 `true`，再启用 `sub2api-autodeploy.timer`。在恢复服务器时也需要重新安装 systemd 单元并核验，避免恢复历史快照后立即部署。
