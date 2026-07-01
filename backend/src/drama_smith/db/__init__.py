"""数据层:SQLAlchemy 模型 + 异步引擎/会话 + 仓储。

- `base.py`:Declarative Base、命名约定、时间戳混入、`get_engine`/`get_session_factory`/
  `dispose_engine`(见 `design.md` D11/D12)。
- `session.py`:`get_session` 请求级会话依赖(事务边界在 services 层,D14)。
- `models/`:ORM 模型(对齐 `database.md`);仓储(`repositories/`)在任务组 4 补全。
"""
