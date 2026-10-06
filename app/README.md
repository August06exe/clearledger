# app/ —— 门户

你在浏览器里看到的界面，加上背后支撑它的服务。地址 `http://127.0.0.1:8620`，只在本机监听。

- `main.py` — 装配入口：启动生命周期、缓存中间件、挂载路由与静态页（业务路由在 `routers/`）
- `routers/` — 六个域路由模块：portal（账套/总览/设置）、lineage（血缘/字典）、reports（报表/口径）、runs（跑批）、workbench（配置工作台）、open_api（钥匙鉴权的对外接口）；`deps.py` 是公共助手
- `config.py` — 全局路径与常量（版本号读仓库根 `VERSION`）
- `services/` — 后端各科室：跑批编排、配置工作台、中文别名层、设置存取、跑批调度
- `static/` — 网页本体（原生 JS + ECharts 图表 + G6 血缘图，无构建链）

改 `static/` 下的文件必须同步升 `static/index.html` 里的 `?v=` 版本串，否则浏览器用旧缓存。改后端要重启门户才生效。
