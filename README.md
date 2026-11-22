# 数据库实例管理系统

基于 Django + Celery 实现的企业内部数据库实例管理系统

- 支持部门、集群、数据库实例管理
- 实例 TCP 端口探测
- 请求耗时统计中间件
- 按部门和集群维度每日统计实例数量
- 密码定时轮换、加密存储，并真实修改目标数据库密码

## 初始化

安装依赖：

```bash
uv sync
```

复制环境变量文件：

```bash
cp .env.example .env
```

修改 `.env` 中的数据库和 Redis 配置。

生成密码加密密钥：

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

把结果填入 `.env`：

```text
CREDENTIAL_ENCRYPTION_KEY=生成的密钥
```

确保 PostgreSQL 中已经创建 `DB_NAME` 对应的数据库，然后执行迁移：

```bash
uv run python manage.py migrate
```

初始化默认的定时任务：

```bash
uv run python manage.py setup_periodic_tasks
```

该命令是幂等的，可以重复执行；会创建或更新以下两条任务：

- `collect-daily-instance-stats`：每天 00:00 统计实例数量
- `rotate-instance-passwords`：每隔 12 小时轮换实例密码

调度配置保存在 `django-celery-beat` 的数据库表中，后续也可以在 Django admin 里调整。

## 启动后端

启动 Django：

```bash
uv run python manage.py runserver 127.0.0.1:8000
```

接口文档：

```text
http://127.0.0.1:8000/api/docs
```

启动 Celery Worker：

```bash
uv run celery -A config worker -l info
```

启动 Celery Beat：

```bash
uv run celery -A config beat -l info
```

## 手动恢复轮换状态

恢复卡在 `rotating` 状态的凭据：

```bash
uv run python manage.py recover_rotations
```

只恢复指定凭据：

```bash
uv run python manage.py recover_rotations --credential-id 12
```

## 运行测试

```bash
uv run python -m pytest -q
```
