# 轨道交通信号设备检修平台

面向轨道交通信号机、转辙机、轨道电路、联锁设备的检修计划、故障处置与验收的一体化检修管理后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 线路区段 | `section` | 线路区段 | 区段编码、区段名称、所属线路 |
| 资料归档 | `archive` | 图纸、竣工资料 | 区段编码、车站、资料名称、版本号、生效日期 |
| 信号机 | `signal` | 信号机 | 设备编号、设备类型、安装位置 |
| 转辙机 | `switch` | 转辙机 | 设备编号、设备型号、安装道岔 |
| 轨道电路 | `track` | 轨道电路 | 设备编号、制式类型、区段长度 |
| 联锁设备 | `interlock` | 联锁设备 | 设备编号、联锁类型、控制范围 |
| 列车防护 | `atp` | 防护设备 | 设备编号、防护等级、覆盖区段 |
| 检修计划 | `plan` | 检修计划 | 计划编号、检修类型、检修对象 |
| 检修任务 | `task` | 检修任务 | 任务编号、关联计划、检修人员 |
| 故障登记 | `fault` | 设备故障 | 故障编号、发生设备、故障现象 |
| 故障处置 | `dispose` | 处置单 | 处置单号、关联故障、处置措施 |
| 器材领用 | `spare` | 器材领用单 | 领用单号、器材名称、器材规格 |
| 电气测试 | `measure` | 测试单 | 测试单号、测试项目、测试设备 |
| 巡视检查 | `patrol` | 巡视单 | 巡视单号、巡视路线、巡视人员 |
| 天窗作业 | `window` | 天窗计划 | 天窗编号、作业类型、作业区段 |
| 监测报警 | `alarm` | 报警事件 | 报警编号、报警类型、报警等级 |
| 验收确认 | `verify` | 验收单 | 验收单号、关联任务、验收项目 |
| 值班交接 | `shift` | 交接记录 | 交接编号、值班班组、值班人员 |
| 状态评估 | `assess` | 评估记录 | 评估编号、评估对象、评估周期 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 资料归档的特殊约定

- 其他模块用内存示例数据（重启复位），资料归档是唯一落盘模块：元数据
  `data/archive/meta.json` 与文件本体 `data/archive/blobs/` 均原子写入，
  服务重启后已归档资料仍在；批量上传的校验结果暂存在 `data/archive/staging/`，
  确认后才入库，过期与中断残留启动时自动清理，不会留下半份资料。
- 批量上传分两步：`POST /api/archive/preflight` 先返回通过/驳回/重复三类清单
  （缺版本号、格式不对、版本号与资料关联不上逐条说明原因），
  `POST /api/archive/commit` 凭 token 整批入库，失败整体回滚。
- 同一份资料按（资料类型、区段、车站、资料名称）识别，再叠加版本号与文件
  SHA256 判重；同一份图纸重复上传只保留一条。
- 竣工资料换版后，历史版本只能通过 `/view` 在线查看，`/download` 返回 403；
  图纸历史版本不受此限。
- 区段编码以线路区段台账为准、车站以联锁设备台账（所属车站）为准，对不上的
  条目驳回；`GET /api/archive/package/zip?区段编码=…` 按区段打包当前生效版本。
