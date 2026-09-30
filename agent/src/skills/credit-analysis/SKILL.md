---
name: credit-analysis
description: "美国/加拿大固定收益与信用分析：国债与 GoC 曲线、IG/HY 公司债、市政债与省级债、机构 MBS、信用利差与 CDS、评级体系（Moody's/S&P/Fitch/DBRS）与违约风险评估。"
category: analysis
tags: [credit, fixed-income, us, canada, ratings, spreads, treasury, goc, municipal, mbs, cds]
---

# Credit Analysis Skill — 美国/加拿大固定收益与信用分析

## 适用场景

当用户提出以下类型问题时，优先调用本 skill：
- 债券定价、YTM 计算、久期/凸性分析
- 企业信用评级、违约概率估算
- 信用利差分析与交易策略
- 市政债 / 省级债、机构 MBS、ABS 信用评估
- 利率风险管理（DV01、关键利率久期）
- 美国国债（UST）/ 加拿大国债（GoC）曲线与信用市场结构分析

> **市场范围**：本 skill 只覆盖美国与加拿大。定价基准为 UST 与 GoC 曲线；发行人评级用
> Moody's / S&P / Fitch / DBRS；申报文件用 SEC EDGAR（10-K/10-Q/8-K）与 SEDAR+。

---

## 一、信用分析框架

### 1.1 信用评级体系

#### 主体评级 vs 债项评级

| 类型 | 定义 | 评级对象 |
|------|------|----------|
| **主体评级（Issuer Rating）** | 发行人整体偿债能力 | 企业、政府、金融机构 |
| **债项评级（Issue Rating）** | 特定债券的信用质量 | 具体债券，考虑抵押品、优先级、契约条款 |

债项评级可高于或低于主体评级（取决于担保结构，例如优先留置权债项评级高于主体评级、
次级债低于主体评级）。

#### 标准普尔 / 穆迪 / DBRS / 惠誉对照

| S&P | Moody's | DBRS | Fitch | 含义 |
|-----|---------|------|-------|------|
| AAA | Aaa | AAA | AAA | 最高信用质量，极低违约风险 |
| AA+/AA/AA- | Aa1/Aa2/Aa3 | AA(high)/AA/AA(low) | AA+/AA/AA- | 高质量，极低违约风险 |
| A+/A/A- | A1/A2/A3 | A(high)/A/A(low) | A+/A/A- | 较高信用质量 |
| BBB+/BBB/BBB- | Baa1/Baa2/Baa3 | BBB(high)/BBB/BBB(low) | BBB+/BBB/BBB- | 投资级下限（IG/HY分水岭） |
| BB+及以下 | Ba1及以下 | BB(high)及以下 | BB+及以下 | 高收益/投机级 |
| D / SD | C / D | D | D / RD | 违约 |

> **北美评级特点**：同一发行人四家机构可能给出不同档位（split rating），尤其在高收益端和
> 结构性融资端。加拿大发行人以 DBRS（Morningstar DBRS）为本国主要机构，DBRS 的
> `(high)` / `(low)` 修饰位与 S&P 的 `+` / `-` 一一对应；对加拿大银行、省级政府与
> covered bond，DBRS 评级往往是本地定价基准。跨机构比较时须结合评级展望
> （正面/稳定/负面）与 Watch 状态。
>
> 美国市政债另有独立的市政评级符号体系（Moody's 市政尺度带数字修饰，如 `Aa1`；
> S&P/Fitch 与全球尺度一致），不要把市政尺度与全球尺度混用。

---

### 1.2 Altman Z-Score 模型

用于预测企业财务困境，原始模型适用于美国上市制造业：

```
Z = 1.2×X1 + 1.4×X2 + 3.3×X3 + 0.6×X4 + 1.0×X5
```

| 变量 | 计算公式 | 含义 |
|------|----------|------|
| X1 | 营运资本 / 总资产 | 流动性 |
| X2 | 留存收益 / 总资产 | 盈利积累 |
| X3 | EBIT / 总资产 | 盈利能力 |
| X4 | 股权市值 / 总负债账面值 | 财务杠杆 |
| X5 | 销售收入 / 总资产 | 资产效率 |

**判断区间**：
- Z > 2.99：安全区（低违约风险）
- 1.81 < Z < 2.99：灰色区（需深入分析）
- Z < 1.81：危险区（高违约风险）

**改进版本**：
- Z'（私有企业）：X4改用股权账面值，临界值2.90/1.23
- Z''（非制造业/新兴市场）：去掉X5，临界值2.60/1.10

**局限性**：
- 基于历史数据，滞后性强
- 不适用金融类企业（杠杆定义不同）——美国/加拿大银行与寿险公司不适用
- 原始系数标定于美国制造业样本；加拿大发行人或重资产能源/公用事业发行人应做行业
  内相对排序，而非直接套用绝对临界值

---

### 1.3 Merton 结构化模型

将公司股权视为对公司资产的看涨期权（执行价格=债务面值）：

**核心假设**：
- 公司资产价值 V 遵循几何布朗运动：`dV = μV dt + σ_V V dW`
- 债务为零息债，面值 D，到期日 T
- 违约仅在 T 时刻发生（欧式违约设定）

**股权定价（BS公式）**：
```
E = V·N(d1) - D·e^(-rT)·N(d2)

d1 = [ln(V/D) + (r + σ_V²/2)T] / (σ_V·√T)
d2 = d1 - σ_V·√T
```

**违约概率（风险中性）**：
```
PD = N(-d2)
```

**距违约距离（DD, Distance to Default）**：
```
DD = [ln(V/D) + (μ - σ_V²/2)T] / (σ_V·√T)
```

**信用利差估算**：
```
信用利差 ≈ -ln[N(d2) + (V/D·e^(rT))·N(-d1)] / T
```

**参数估算方法**（联立方程组）：
1. E = V·N(d1) - D·e^(-rT)·N(d2)
2. σ_E·E = N(d1)·σ_V·V

> 无风险利率取同期限 UST（或 GoC）零息利率；股权波动率可用美股/US 上市期权隐含
> 波动率标定，加拿大发行人以 TSX 挂牌股票的期权或历史波动率替代。

---

### 1.4 KMV 模型（预期违约频率 EDF）

KMV 是 Merton 模型的商业化实现，由穆迪收购：

**步骤**：
1. 用股价和股权波动率反推资产价值 V 和资产波动率 σ_V
2. 计算违约触发点（Default Point）：`DP = 短期债务 + 0.5×长期债务`
3. 计算距违约距离：`DD = (V - DP) / (V × σ_V)`
4. 通过历史违约数据库将 DD 映射为 EDF（非正态映射）

**与 Merton 的区别**：
- 违约触发点不是全部债务，而是短期+半长期
- DD→EDF 映射基于实证数据库，非正态分布假设
- EDF 是真实世界概率，而非风险中性概率

**EDF 参考区间**（约）：
- EDF < 0.1%：投资级
- 0.1%–1%：BBB-BB 级
- 1%–5%：B 级
- EDF > 5%：CCC 及以下

> Moody's 的北美违约数据库是该映射的商业输入；本仓库没有该数据的授权，因此只能用
> 参考区间做量级校验（见 §5.5）。

---

### 1.5 信用评分卡方法论

适用于消费信贷/ABS 底层资产分析（美国信用卡 ABS、汽车 ABS、加拿大 covered bond
底层资产）：

**建模流程**：
1. **数据准备**：收集历史贷款数据，定义违约标签（如逾期90天+）
2. **特征工程**：WOE（Weight of Evidence）编码
3. **特征选择**：IV值（Information Value）筛选，IV>0.02保留
4. **模型训练**：Logistic Regression（主流）、XGBoost
5. **评分转换**：`Score = A - B×ln(odds)`，通常基准分600，PDO=20

**WOE 和 IV 计算**：
```python
WOE_i = ln(好样本比例_i / 坏样本比例_i)
IV_i = (好样本比例_i - 坏样本比例_i) × WOE_i
总IV = Σ IV_i
```

**IV 参考标准**：
- IV < 0.02：无预测力
- 0.02–0.1：弱预测力
- 0.1–0.3：中等预测力
- IV > 0.3：强预测力

---

## 二、固收产品分析

### 2.1 国债与政府债

#### 收益率曲线分析

**即期利率曲线（Zero Curve）**：各期限无风险零息债收益率，通过 Bootstrap 方法从附息债提取。

**远期利率曲线（Forward Curve）**：
```
f(T1, T2) = [(1+r2)^T2 / (1+r1)^T1]^(1/(T2-T1)) - 1
```

**期限利差**：
- 10Y-2Y：经济周期预判指标，负值通常预示衰退
- 10Y-1Y：流动性偏好衡量指标
- 30Y-10Y：超长端供需判断

**收益率曲线形态**：
| 形态 | 特征 | 经济含义 |
|------|------|----------|
| 正斜率（Normal） | 长端>短端 | 经济扩张预期 |
| 平坦（Flat） | 各期限相近 | 经济转折点 |
| 倒挂（Inverted） | 短端>长端 | 衰退信号 |
| 驼峰（Humped） | 中端最高 | 流动性分层 |

#### 美国国债与加拿大国债收益率曲线特点

**美国国债（UST）**：
- 基准曲线：UST on-the-run 曲线，关键点位 1M/3M/6M/1Y/2Y/3Y/5Y/7Y/10Y/20Y/30Y
- 10Y UST 是全球无风险利率与信用定价的最终锚，30Y 由养老金与保险需求定价
- 通胀挂钩品种：TIPS（breakeven inflation = 名义利率 - TIPS 实际利率）
- 短端由联邦基金目标利率与 SOFR 曲线牵引；SOFR 是美元浮动利率债与衍生品的基准
- 信用定价基准：G-Spread（vs UST）、I-Spread（vs SOFR swap）

**加拿大国债（GoC）**：
- 基准曲线：GoC benchmark bond 曲线，关键点位 2Y/3Y/5Y/10Y/30Y，短端辅以
  T-bill 与 CORRA
- 10Y GoC 是加元信用（省级债、加拿大银行债、covered bond、公司债）的定价基准
- 通胀挂钩品种：Real Return Bonds（RRB）
- CORRA 是加元浮动利率债与衍生品的基准（替代已退出的 CDOR）
- 加拿大发行人常同时发行 CAD 与 USD 债，须比较 GoC + spread 与 UST + spread 的
  交叉货币基差（cross-currency basis）后判断相对价值

---

### 2.2 企业债分析

#### 核心指标

**票面利率（Coupon Rate）**：发行时约定，按面值计息。

**到期收益率 YTM（Yield to Maturity）**：
使 债券现值 = 市场价格的内部收益率：
```
P = Σ [C/(1+y)^t] + F/(1+y)^n
```
其中 C=票息，F=面值，y=YTM，n=期数。

**当期收益率（Current Yield）**：`CY = 年票息 / 市场价格`（忽略本金损益）

**修正久期（Modified Duration）**：
```
MD = -dP/P ÷ dy = Macaulay Duration / (1+y/m)
```
含义：利率每变化1%，债券价格变化约MD%（反向）。

**凸性（Convexity）**：
```
CX = [Σ t(t+1)·CF_t/(1+y)^(t+2)] / P
价格变化修正：ΔP/P ≈ -MD·Δy + 0.5·CX·(Δy)²
```

#### 债券价格公式（实现）

定价函数是仓库里的实测代码，直接 import，**不要在会话里重新手写**：

```python
from src.quantlib.fixedincome import bond_price

bond_price(face=100, coupon_rate=0.05, ytm=0.04, n_periods=5, freq=1)
# -> 104.4518...   5年期、票息5%、YTM=4%、年付
```

两个约定在这里是**显式参数**，不是隐含假设：

- `compounding`：`"discrete"`（默认，每年 `freq` 次离散复利，即上面 `P = Σ C/(1+y/m)^t` 的形式）或 `"continuous"`。
- 日算基准：`bond_price` 按整数付息期贴现，因此返回的是**付息日**的价格（净价，应计为 0）。
  非付息日结算要另加应计利息才是全价（脏价）：

```python
import datetime as dt
from src.quantlib.fixedincome import accrued_interest

# 美式公司债惯例：30/360、半年付息
accrued = accrued_interest(
    face=100, coupon_rate=0.05, freq=2,
    last_coupon=dt.date(2024, 1, 15),
    settlement=dt.date(2024, 4, 15),
    next_coupon=dt.date(2024, 7, 15),
    day_count="30/360",   # ACT/365F(默认) | ACT/360 | ACT/ACT | 30/360 | 30E/360
)                          # -> 1.25
dirty_price = bond_price(100, 0.05, 0.04, 10, 2) + accrued
```

**北美日算基准对应关系**（选错日算会系统性偏掉应计利息）：

| 品种 | 惯例日算 | 付息频率 |
|------|----------|----------|
| UST（含 TIPS） | ACT/ACT (ICMA) | 半年 |
| GoC / 省级债 | ACT/ACT (ICMA) | 半年 |
| 美国公司债、市政债 | 30/360 | 半年 |
| 加拿大公司债 | ACT/365F 或 ACT/ACT | 半年 |
| 美国浮动利率票据（FRN，SOFR） | ACT/360 | 季度 |

---

### 2.3 可转债（纯债部分）

> 本节只做**信用视角**：纯债底（bond floor）与违约情形下的回收。转股期权的定价见
> `options-advanced` skill。

**纯债价值（Bond Floor）**：
```
纯债价值 = Σ [票息/(1+r_straight)^t] + 面值/(1+r_straight)^n
```
其中 r_straight 为同评级同期限直债收益率（美国发行人取 UST + 同评级公司债利差；
加拿大发行人取 GoC + 利差）。

**转股溢价率与纯债溢价率**：
- 转股溢价率 = (可转债价格 - 转股价值) / 转股价值
- 纯债溢价率 = (可转债价格 - 纯债价值) / 纯债价值

**北美可转债（US-listed converts / TSX-listed converts）的信用要点**：
- 发行人以高收益与未评级科技/生物科技公司为主，信用分析的重点是**现金消耗速度**
  与**再融资窗口**，而不是资产抵押
- 多数美国可转债为 144A 发行、含 3 年左右投资者回售权（put）与发行人赎回权（call）；
  回售权是信用分析的关键——它把再融资风险提前到首个 put date
- 转股价值上升会降低公司的实际杠杆（转股即去杠杆），因此信用质量与股价正相关，
  这是可转债特有的"负相关信用/权益"结构
- 下修/反稀释条款（anti-dilution）影响潜在摊薄与转股后杠杆改善幅度

---

### 2.4 ABS/MBS 分析

#### 底层资产分析框架

**资产质量指标**：
- 加权平均票息（WAC）
- 加权平均剩余期限（WAM）
- 加权平均贷款价值比（LTV）
- 历史逾期率（DPD 30/60/90+）
- 累计违约率（CDR，Cumulative Default Rate）

**早偿率模型**：
- CPR（Conditional Prepayment Rate）：年化早偿率
- SMM（Single Monthly Mortality）：月早偿率
  ```
  CPR = 1 - (1 - SMM)^12
  SMM = 1 - (1 - CPR)^(1/12)
  ```
- PSA 模型：标准早偿假设（PSA100 = 前30个月线性增至6%/年，之后6%/年恒定）

**分层结构（Tranche）分析**：
- 优先级（Senior）：最先受偿，评级最高
- 夹层（Mezzanine）：次级受偿
- 劣后级（Equity/Junior）：首先吸收损失，超额利差归属

**关键风险指标**：
```
增信倍数 = (底层资产池规模 - 优先级规模) / 优先级规模
超额利差 = 底层资产池利率 - 优先级融资成本 - 服务费
```

**美国机构 MBS（agency MBS）**：
- 发行人：Fannie Mae / Freddie Mac（信用风险由联邦机构承担）、Ginnie Mae
  （由美国政府信用担保，底层为 FHA/VA 贷款）
- 核心风险不是信用风险，而是**负凸性**：利率下行时早偿加速、久期缩短；利率上行时
  早偿放缓、久期拉长（extension risk）。因此用 OAS 与 effective duration 定价，
  而非名义利差（见 §5.1 的 `effective_duration`）
- 定价基准：current coupon vs 10Y UST 利差；UMBS 是 TBA 市场的标准品种
- 非机构 RMBS / CMBS 才有真正的信用风险，须看 CDR、严重程度（severity）与
  增信结构

**加拿大 MBS 与 covered bond**：
- 加拿大住宅按揭主要由 CMHC 担保的 NHA MBS 池化，再由银行发行
  Canada Mortgage Bonds（CMB），信用风险极低
- 银行以 NHA MBS 为担保发行 covered bond，评级通常为 AAA（DBRS/Moody's），
  定价为 GoC + spread
- 加拿大没有美国式的 agency 结构；信用分析重点在**省级住房机构**与银行
  balance sheet 上的按揭敞口

---

### 2.5 市政债与省级债信用分析

#### 美国市政债（Municipal Bonds）

信用分析的核心是**收入来源的独立性**，而非公司报表：

| 类型 | 偿债来源 | 典型风险 |
|------|----------|----------|
| 一般责任债（GO） | 发行人的征税权（ad valorem tax） | 税基萎缩、养老金与 OPEB 缺口 |
| 有限税 GO（limited-tax GO） | 法定税率上限内的税收 | 税率封顶导致偿债能力受限 |
| 基本服务收入债 | 水/电/污水等垄断性收费 | 费率政治阻力、资本开支缺口 |
| 企业收入债 | 机场、收费公路、港口 | 客流/车流预测偏差、竞品分流 |
| 特殊税/拨款债 | 销售税、TIF、联邦/州拨款 | 拨款依赖、项目完工风险 |
| 康斗/IDR/CDD 债 | 特定地块评估费 | 高度集中、违约传导快 |

**四维评估模型**：

| 维度 | 核心指标 | 权重 |
|------|----------|------|
| 经济与税基 | 税基规模与增速、人口/就业、纳税人集中度（top-10 占比） | 35% |
| 财务与储备 | 一般基金余额/收入比、流动性、预算平衡记录 | 25% |
| 债务与养老金 | 净直接债务/全值、债务偿还率、净养老金负债/收入 | 25% |
| 治理与管理 | 管理层稳定性、披露及时性、州监督机制（如 EMU/Act 47） | 15% |

**市政债特有风险信号**：
- 一般基金余额/收入 < 5%（缓冲不足）
- 养老金与 OPEB 净负债/收入 > 200%（长期刚性支出挤压）
- 依赖一次性收入（资产出售、借款）平衡经常性预算
- 收入债的 DSCR < 1.2x，或费率上调长期滞后于成本
- 州政府截留/紧急管理介入、评级列入负面观察

**市政债估值溢价结构**（参考）：
```
免税市政债收益率 ≈ 同期限 UST - 税收溢价 + 流动性溢价(5-40bp) + 信用溢价(0-250bp)
```
税收溢价由边际税率决定（免税等价收益率 = 免税收益率 / (1 - 边际税率)）；
超长期市政债还叠加**保险与集中度**因素。应税市政债（taxable muni）则直接用
UST + spread 定价。

#### 加拿大省级债与机构债（Provincial / Agency）

- 发行人：10 个省 + 3 个地区，加上省级 Crown corporation 与代理机构
  （如 Ontario Financing Authority、Financement-Québec、CMHC、Farm Credit Canada、
   provincial utilities）
- 评级：以 DBRS 为主，省级债通常落在 AA(low)/A(high) 区间，少数弱势省份更低；
  四大银行与主要 Crown corp 多为 AA(low) 及以上
- 定价：GoC + provincial spread，spread 由**财政实力 + 流动性 + 发行量**决定，
  而非公司式违约概率——加拿大省级债历史违约几乎为零，利差主要反映流动性与
  供给压力
- 关键指标：净债务/GDP、净债务/收入、利息支出/收入、联邦转移支付依赖度、
  原油/资源收入占比（AB/SK/NL 敏感）

**省级债评估要点**：

| 维度 | 核心指标 | 关注点 |
|------|----------|--------|
| 财政实力 | 净债务/GDP、债务偿还率、预算平衡 | 趋势比绝对水平更重要 |
| 经济结构 | 资源依赖度、税基多元化、人口趋势 | 单一资源省份周期性更强 |
| 流动性 | 本币融资能力、发行计划、二级市场深度 | 小省份流动性溢价明显 |
| 制度支持 | 联邦转移支付（CHT/CST/Equalization） | 等式化支付缓冲弱省压力 |

**风险预警信号（红线）**：
- 净债务/GDP 连续多年上升且无财政整顿计划
- 依赖短期票据滚动（treasury bill / short-term paper）为长期资本开支融资
- 省级 Crown corp 的债务/权益比率恶化且需省级担保
- 资源收入假设显著高于远期曲线，预算平衡依赖价格假设
- 评级展望连续两次下调或列入 Negative Watch

---

## 三、利率风险管理

### 3.1 久期体系

#### Macaulay Duration（麦考利久期）

时间加权现金流现值之和，单位为"年"：
```
D_mac = Σ [t × CF_t/(1+y)^t] / P
```

#### Modified Duration（修正久期）

利率敏感性度量：
```
D_mod = D_mac / (1 + y/m)
ΔP ≈ -D_mod × P × Δy
```

#### Effective Duration（有效久期）

适用于含权债券（可赎回公司债、agency MBS、市政债 callable、加拿大 covered bond
call 条款）：
```
D_eff = (P_down - P_up) / (2 × P_0 × Δy)
```
其中 P_down/P_up 为利率下移/上移Δy后的价格。

#### Dollar Duration（久期金额）

```
Dollar Duration = D_mod × P × 面值
```

---

### 3.2 凸性（Convexity）

衡量久期对利率的敏感性（二阶效应）：

```
C = Σ [t(t+1) × CF_t/(1+y)^(t+2)] / P

价格精确估算：
ΔP/P ≈ -D_mod·Δy + 0.5·C·(Δy)²
```

**凸性的价值**：正凸性使债券在利率下行时涨幅大于预期（利率上行时跌幅小于预期），
因此正凸性债券比负凸性债券（如可赎回公司债、agency MBS、callable 市政债）更受青睐。

---

### 3.3 DV01（基点价值）

利率变动1基点（0.01%）导致的价格变化：
```
DV01 = D_mod × P × 0.0001
```

组合层面：`Portfolio DV01 = Σ (DV01_i × 持仓量_i)`

**用途**：利率对冲比率计算
```
对冲比率 = DV01_被对冲头寸 / DV01_对冲工具
```
美国市场常用 UST 现券、UST 期货（TY/US/ZB）或 SOFR swap 做对冲；
加拿大市场常用 GoC 现券或 CGB 期货。

---

### 3.4 关键利率久期（Key Rate Duration, KRD）

衡量收益率曲线各关键期限平行移动1bp对价格的影响：
- 常用关键点：1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y
- `KRD_i = -ΔP/(P × Δy_i)`（仅第i个关键利率变动1bp）
- `Σ KRD_i ≈ D_mod`（各关键利率久期之和约等于修正久期）

**应用**：
- 识别组合对特定期限利率的暴露
- 精确对冲非平行移动风险（扭曲/蝶式）——例如用 2Y/10Y/30Y UST 三腿对冲
  信用组合的曲线风险

---

### 3.5 免疫策略

**久期匹配（Duration Matching）**：
使资产组合久期 = 负债久期，对利率平行移动免疫。
条件：`Σ (w_i × D_i) = D_liability`

**现金流匹配（Cash Flow Matching）**：
直接匹配每期现金流，彻底消除再投资风险，但灵活性差、成本高。美国养老金与保险
负债常用 UST STRIPS 或长期高评级公司债构建现金流匹配组合。

**条件免疫（Contingent Immunization）**：
当组合价值超过安全底线时主动管理，跌至底线时切换为被动免疫。

**再平衡频率**：
- 久期随时间漂移，需定期（季度/月度）再平衡
- 利率大幅变动（>50bp）后立即再平衡

---

## 四、信用利差分析

### 4.1 信用利差的构成

```
信用利差（Credit Spread）= 违约风险溢价 + 流动性溢价 + 税收溢价（部分市场）
```

| 组成部分 | 影响因素 | 量化方式 |
|----------|----------|----------|
| 违约风险溢价 | 评级、行业、财务状况、宏观周期 | CDX/CDS报价、模型测算 |
| 流动性溢价 | 发行规模、剩余期限、市场深度 | TRACE 买卖价差、换手率 |
| 税收溢价 | 市政债利息免税（美国联邦/州层面） | 免税等价收益率换算 |

**利差衡量基准**：
- G-Spread（vs UST/GoC 同期限）、I-Spread（vs SOFR/CORRA swap）、
  Z-Spread（零息利差）、OAS（期权调整利差）
- 美国市政债：以 MMD/AAA 市政曲线为基准，报"spread to MMD"；跨市场比较须先做
  免税等价换算
- 加拿大信用：以 GoC 曲线为基准报 spread；同时发行的 USD 债用 UST 基准，
  须叠加交叉货币基差后比较

**CDX 与 CDS**：
- CDX.NA.IG / CDX.NA.HY 是北美信用风险的一阶市场指标，比现券利差反应更快
- 单名 CDS 用于对冲与相对价值（basis trade：CDS vs 现券）
- 对加拿大发行人，CDS 流动性集中在六大银行与主要省级/能源发行人

**OAS（Option-Adjusted Spread）**：
剥离嵌入期权价值后的信用利差，适用于含权债比较（callable 公司债、agency MBS）：
```
P = Σ CF_t / (1 + r_t + OAS)^t
```

---

### 4.2 信用利差曲线形态

**正斜率**（常见）：长期利差 > 短期利差，反映期限不确定性叠加。

**平坦/倒挂**：
- 市场对长期信用风险乐观（平坦）
- 短期流动性危机/再融资困境（倒挂），警示信号

**信用利差与国债收益率的相关性**：
- 经济扩张：信用利差收窄（风险偏好上升）
- 经济衰退/信用事件：信用利差走阔
- "逃向质量"效应：UST/GoC 收益率下行+信用利差扩大，双重打击高收益债

---

### 4.3 信用利差变化的驱动因素

**宏观因素**：
- GDP增速、ISM 制造业 PMI、加拿大 Ivey PMI：预期改善→利差收窄
- 货币政策（Fed / Bank of Canada）：宽松→流动性溢价下降
- 信用事件（违约潮）：系统性利差走阔

**行业因素**：
- 行业政策与监管（能源管道审批、药品定价、银行资本规则）
- 行业景气周期（油气价格、房地产、零售）
- 再融资环境（高收益债一级市场是否"开窗"）

**个券因素**：
- 评级调整（下调→利差跳升），或四家机构间的 split rating 变化
- 财务数据变化（杠杆、利息覆盖、自由现金流）
- 到期压力（临近到期→流动性利差增加）

---

### 4.4 信用利差交易策略

**利差压缩交易（Spread Tightening）**：
做多被低估（高利差）信用债，做空国债对冲利率风险。
- 适用场景：经济复苏初期、央行宽松周期

**利差扩大交易（Spread Widening）**：
做空信用债（通过 CDS 或 CDX），做多国债。
- 适用场景：经济下行、信用事件频发

**跨评级利差交易**：
做多高收益/做空投资级（利差压缩时），或相反。

**蝶式利差交易（Butterfly）**：
做多中期、做空短端和长端，获利于信用曲线中段的相对价值。

**北美常用工具**：
- CDX.NA.IG / CDX.NA.HY 指数与单名 CDS：对冲与表达信用观点
- 信用风险缓释与指数期权（CDX 期权）、iTraxx 用于跨市场
- UST 期货 / CGB 期货：对冲利率久期风险
- ETF（LQD/HYG/MUB/IGLB 等）用于快速暴露与流动性替代
- 加拿大信用：省级债 vs GoC、银行债 vs 省级债、CAD vs USD 交叉货币相对价值

---

## 五、Python 实现（quantlib）

本章的模型**已经是仓库里的实测代码**，位于 `src/quantlib/fixedincome.py`（债券数学 + 曲线拟合）
与 `src/quantlib/credit.py`（Altman Z / Merton-KMV / 利差）。两个模块都有对应的
`tests/quantlib/test_fixedincome.py`、`tests/quantlib/test_credit.py`，久期与 DV01 是对
"重新定价 ±1bp" 逐点核过的。

**直接 import 调用，不要在会话里重写这些公式。** 手写一遍既拿不到测试保障，也不可复现。

一律的单位约定：利率与比率是小数（`0.05` 表示 5%），期限与时间跨度是**年**，
久期/凸性的返回值是**年 / 年²**（不是付息期数），带 `_bp` 后缀的才是基点。

### 5.1 债券定价、久期与 DV01

```python
from src.quantlib.fixedincome import (
    bond_price, ytm_solve, macaulay_duration, modified_duration,
    convexity, dv01, effective_duration,
)

face, coupon, ytm, n, freq = 100, 0.05, 0.04, 5, 1

price = bond_price(face, coupon, ytm, n, freq)          # 104.4518
ytm_solve(price, face, coupon, n, freq)                 # 0.04（价格反解 YTM）

macaulay_duration(face, coupon, ytm, n, freq)           # 4.5571 年
modified_duration(face, coupon, ytm, n, freq)           # 4.3818 年
convexity(face, coupon, ytm, n, freq)                   # 24.4766 年²
dv01(face, coupon, ytm, n, freq, par_amount=1_000_000)  # 457.69 美元/bp
```

**参数要点**

| 参数 | 说明 |
|------|------|
| `freq` | 每年付息次数，`1`=年付、`2`=半年付（UST/GoC/公司债标准）。所有函数都接受，绝不写死 |
| `compounding` | `"discrete"`（默认）或 `"continuous"`。连续复利下修正久期恒等于 Macaulay 久期 |
| `par_amount` | `dv01` 的持仓面值，默认 100 万；对冲的市值按 `par_amount * price / face` 计 |
| `bracket` | `ytm_solve` 的求根区间，默认 `(-0.5, 10.0)`，覆盖所有可交易债券 |

含权债（可赎回公司债、agency MBS、callable 市政债）的现金流会随利率移动，解析久期
不适用，改用重新定价法：

```python
d_eff = effective_duration(reprice=lambda y: my_oas_model(y), yield_level=0.04, bump=1e-4)
```

`reprice` 必须自带赎回/早偿逻辑；`effective_duration` 只负责 `(P_down - P_up) / (2·P₀·Δy)`。

### 5.2 收益率曲线拟合（Nelson-Siegel / Svensson）

```python
import numpy as np
from src.quantlib.fixedincome import fit_yield_curve, nelson_siegel, svensson

maturities = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30])
yields     = np.array([0.019, 0.020, 0.022, 0.024, 0.025, 0.027, 0.028, 0.029, 0.033, 0.035])

fit = fit_yield_curve(maturities, yields, model="svensson")
fit.params      # (beta0, beta1, beta2, beta3, lambda1, lambda2)
fit.rmse        # 拟合残差（小数，与输入同单位）
fit(4.5)        # 任意期限插值 -> 该点即期利率
fit([1, 5, 10]) # 也接受数组
```

（上例的期限网格即 UST/GoC 的关键点位；把 Fed 的 H.15 或 Bank of Canada 的
benchmark bond yields 填进去即可拟合本币曲线。）

`fit_yield_curve` 返回一个 **`CurveFit` 对象**（不是 `(params, func)` 元组）：它本身可调用，
同时带 `model` / `params` / `rmse` 三个只读字段。`model` 取 `"nelson_siegel"`（4 参数）
或 `"svensson"`（6 参数，双曲率因子）。

拟合方式是**可分离最小二乘**：给定衰减参数 λ 后 β 是线性的，用 OLS 精确求解，
只对 1~2 个 λ 做网格 + Nelder-Mead 搜索。这一点很要紧——对全部参数一起做单点起始的
L-BFGS-B（本 skill 早先模板的做法）**连自己生成的曲线都还原不回来**：
在 10 个期限的无噪 Nelson-Siegel 曲线上它停在 RMSE 6.4e-4（6.4bp），
而现在这个实现是 4.0e-14。

需要直接按参数取值（例如做因子分解、做情景模拟）时用底层函数：

```python
nelson_siegel(tau=[1, 5, 10], beta0=0.045, beta1=-0.02, beta2=0.03, lambda1=2.5)
svensson(tau=5.0, beta0=0.05, beta1=-0.03, beta2=0.04, beta3=-0.02,
         lambda1=1.2, lambda2=8.0)
```

`beta0` 是水平因子（长端渐近利率），`beta0 + beta1` 是瞬时短端利率，
`beta2` / `beta3` 是曲率因子，`lambda*` 是衰减速度（年）。传标量返回标量，传数组返回数组。

### 5.3 Altman Z-Score 计算

```python
from src.quantlib.credit import altman_z_score

z = altman_z_score(
    working_capital=200,      # X1 分子：流动资产 - 流动负债
    retained_earnings=300,    # X2 分子：留存收益
    ebit=150,                 # X3 分子：息税前利润
    equity_value=900,         # X4 分子：original 用股权市值，prime/double_prime 用账面净资产
    total_liabilities=600,    # X4 分母：全部负债的账面值
    total_assets=1000,        # X1/X2/X3/X5 的分母
    revenue=1200,             # X5 分子；double_prime 不需要，可省略
    model="original",         # original | prime | double_prime
)

z.z_score            # 3.255
z.zone               # "safe" | "grey" | "distress"
z.label_zh           # "安全区（低违约风险）"
z.components         # {"x1": 0.20, "x2": 0.30, "x3": 0.15, "x4": 1.50, "x5": 1.20}
z.safe_threshold     # 2.99
z.distress_threshold # 1.81
```

三个变体的系数与临界值在 `ALTMAN_MODELS` 里，与 §1.2 的表格一一对应：

| `model` | 适用对象 | 系数 (X1..X5) | 安全 / 危险 |
|---------|----------|---------------|-------------|
| `original` | 上市制造业（Altman 1968） | 1.2 / 1.4 / 3.3 / 0.6 / 1.0 | > 2.99 / < 1.81 |
| `prime`（Z'） | 私有企业，X4 改用账面净资产 | 0.717 / 0.847 / 3.107 / 0.420 / 0.998 | > 2.90 / < 1.23 |
| `double_prime`（Z''） | 非制造业 / 新兴市场，去掉 X5 | 6.56 / 3.26 / 6.72 / 1.05 / — | > 2.60 / < 1.10 |

> **X4 的分母是「全部负债」，不是「有息负债」。** §1.2 的变量表写的是"总负债账面值"，
> 参数名 `total_liabilities` 与模型定义一致。用有息负债代入会系统性高估 Z 值。

同一份报表在三个变体下给出的分区可以不同（上例：`original` 安全区、`prime` 灰色区），
这正是重新标定的意义，不是矛盾。对加拿大发行人（尤其是能源与公用事业），
`double_prime` 变体的行业可比性通常更好。

### 5.4 信用利差分析

```python
from src.quantlib.credit import credit_spread_analysis, spread_term_structure

df = credit_spread_analysis(
    bond_yields=bond_ytm_series,       # pd.Series，索引=日期
    risk_free_yields=ust_ytm_series,   # 必须与上面同一个索引（或 GoC 同期限）
    window=252,                        # 滚动窗口（交易日）
    lookback_periods=21,               # 慢速变化列的回溯期
    signal_z=1.5,                      # 触发 rich/cheap 的 |z| 阈值
    input_unit="percent",              # percent | decimal | bp
)
```

返回的 DataFrame 列固定为：`spread_bp`、`rolling_mean_bp`、`rolling_std_bp`、`z_score`、
`historical_percentile`、`change_1p_bp`、`change_lookback_bp`、`signal`。
`signal` 取 `"rich"`（利差偏低、偏贵）/ `"neutral"` / `"cheap"`（利差偏高、偏便宜）。

> **`historical_percentile` 是全样本排名，带前视偏差，不能当回测信号用。** 它把每一行
> 和它**之后**的行一起排序——同一天的分位数会随着新数据到来而改变（实测：同一行在 50 行
> 切片上是 0.02，在 100 行上变成 0.01）。这是原模板的行为，保留是为了不静默改变口径。
> `z_score` 与 `signal` 走滚动窗口，是因果的，要做信号用这两个。

```python
grid = spread_term_structure(
    issuers={"IG 工业": {1: 0.045, 3: 0.050, 5: 0.055},
             "HY 能源": {1: 0.080, 3: 0.095, 5: 0.110},
             "加拿大省级": {1: 0.033, 3: 0.038, 5: 0.043}},
    risk_free_curve={1: 0.020, 3: 0.022, 5: 0.025},   # UST 或 GoC 曲线
    input_unit="decimal",   # 注意默认值与上面那个函数不同
    decimals=1,
)
# 行=发行人，列=1Y_spread_bp / 3Y_spread_bp / 5Y_spread_bp
```

> **输入单位必须自己确认。** 两个函数的历史默认值不一致：`credit_spread_analysis`
> 默认收益率是**百分数**（`3.2` 表示 3.2%），`spread_term_structure` 默认是**小数**（`0.032`）。
> 默认值保留了原模板的行为，但 `input_unit` 现在是显式参数——喂数据前先看清楚手里的序列是哪一种，
> 搞反就是 100 倍的利差。

### 5.5 Merton 结构化模型与 KMV

```python
from src.quantlib.credit import (
    merton_model, merton_asset_solve, distance_to_default,
    kmv_default_point, kmv_distance_to_default, edf_reference_band,
)

m = merton_model(
    equity_value=100,   # 股权市值
    equity_vol=0.40,    # 股权年化波动率
    debt_face=100,      # 债务面值（简化为单笔零息债）
    risk_free=0.03,     # 连续复利无风险利率（同期限 UST/GoC 零息）
    horizon=1.0,        # 债务到期年限
    asset_drift=None,   # 距违约距离用的资产漂移；None = 用 risk_free（风险中性口径）
)

m.asset_value           # 197.04  反推出的资产价值
m.asset_vol             # 0.2030  反推出的资产波动率
m.distance_to_default   # 3.3868  asset_drift=None 时等于 d2
m.default_probability   # 0.000354  风险中性违约概率 N(-d2)
m.credit_spread_bp      # 0.176 bp
```

联立方程（§1.3 的两式）在 `merton_asset_solve` 里解，且是在**对数空间**求解的，
所以根不会跑到负资产或负波动率上；不收敛会直接抛 `ValueError`，不会静默返回垃圾解。

**Merton 与 KMV 的 DD 是两个不同的量，不要混用**：

```python
# Merton：对数空间、带漂移与期限
distance_to_default(asset_value=200, asset_vol=0.25, default_point=100,
                    horizon=2.0, drift=0.06)

# KMV：线性缺口，无期限无漂移，违约点只含短债 + 部分长债
dp = kmv_default_point(short_term_debt=100, long_term_debt=200,
                       long_term_weight=0.5)      # -> 200
kmv_distance_to_default(asset_value=1000, asset_vol=0.25, default_point=dp)  # -> 3.2

edf_reference_band(3.2)   # -> (0.001, 0.01)，即 §8 表里的 0.1%–1% 档
```

> `edf_reference_band` 只是把 §8 那张"DD → EDF"经验表做成了查表函数。
> 真正的 KMV EDF 来自穆迪的专有违约数据库，这里的输出只能当**量级校验**，
> 绝不能当作已标定的违约概率报出去。

**风险中性 vs 真实世界**：`asset_drift` 只影响 `distance_to_default`，不影响 `d2`、
`default_probability` 和 `credit_spread`——后三者按定义就是风险中性的。想看真实世界口径，
传一个预期资产回报进去，然后配 `edf_reference_band` 读档，不要拿 `N(-dd)` 当 EDF 报。

---

## 六、美国与加拿大固收市场结构

### 6.1 市场结构

#### 交易场所与监管

| 维度 | 美国 | 加拿大 |
|------|------|--------|
| 监管机构 | SEC、FINRA、MSRB（市政）、CFTC（衍生品）、Fed/财政部（国债） | CSA/各省证监会、IIROC/CIRO、Bank of Canada、OSFI |
| 国债一级市场 | 财政部 auction（competitive/non-competitive），一级交易商 | Bank of Canada auction，primary dealers |
| 公司债交易 | OTC 为主，TRACE 事后透明；组合交易（portfolio trading）占比上升 | OTC 为主，通过 dealer 报价；CANDEAL 等电子平台 |
| 市政债 | OTC + EMMA 披露（MSRB） | 不适用（对应品种为省级债/机构债） |
| 结算 | Fedwire / DTCC，T+1（国债/公司债） | CDS（Canadian Depository for Securities），T+1 |
| 基准利率 | SOFR（替代 LIBOR） | CORRA（替代 CDOR） |
| 流动性 | 极高（UST）；公司债分层明显 | 高（GoC/省级债）；公司债流动性弱于美国 |

#### 主要债券品种

| 品种 | 发行主体 | 监管/注册 | 信用风险 |
|------|----------|-----------|----------|
| 美国国债（UST） | 美国财政部 | 无限制（债务上限约束） | 无（主权信用，AAA/AA+） |
| TIPS | 美国财政部 | 同上 | 无（本金随 CPI 调整） |
| 机构债（Agency） | Fannie/Freddie/FHLB/Farm Credit | FHFA/OFHEO 监管 | 极低（GSE 信用） |
| 市政债（Muni） | 州/地方政府、学区、公共机构 | SEC 15c2-12 + MSRB/EMMA | 中低（视税基与收入来源） |
| 公司债（IG） | 美国企业 | SEC 注册（10-K/10-Q/8-K 披露） | 低-中 |
| 公司债（HY） | 美国企业、部分 144A | SEC 或 144A | 中高 |
| ABS / 非机构 MBS / CMBS | SPV | SEC 注册 + Reg AB II | 取决于底层资产 |
| Agency MBS（UMBS/CMO） | Fannie/Freddie/Ginnie | FHFA/SEC | 极低信用风险，高负凸性 |
| GoC 国债 | 加拿大政府 | 无限制 | 无（主权信用，AAA） |
| RRB（实际回报债） | 加拿大政府 | 同上 | 无（本金随 CPI 调整） |
| 省级债（Provincial） | 省政府 | 各省证券法 | 极低-低（DBRS 主导评级） |
| 加拿大机构债 | CMHC、FCC、省级 Crown corp | 联邦/省法规 | 极低（部分有政府担保） |
| 加拿大公司债 | 加拿大企业（TSX 上市为主） | 各省证券法 + SEDAR+ 披露 | 低-中 |
| 加拿大银行债 / covered bond | 六大银行 | OSFI + 各省证券法 | 低（covered bond 通常 AAA） |

---

### 6.2 市政债与省级债深度分析要点

**一级市场分析（发行定价）**：
1. 核查发行人类型（GO / limited-tax GO / 收入债）与偿债来源的独立性
2. 审查收入债的费率表、服务区域与竞争性替代（如收费公路 vs 免费公路）
3. 评估税基规模、纳税人集中度与增长趋势
4. 分析养老金与 OPEB 净负债（美国市政债最主要的长期刚性支出）
5. 加拿大省级债：核对预算文件中的净债务/GDP、债务偿还率与资源收入假设

**二级市场分析（持仓估值）**：
1. 跟踪利差变化（市政债 vs MMD/UST；省级债 vs GoC）
2. 关注披露事件（EMMA 的 15c2-12 重大事件通知；省级评级展望变化）
3. 监测再融资节奏（call date、put date、到期墙 vs 新发计划）
4. 关注政策与政治事件（州监督介入、选举后的财政优先级、联邦转移支付调整）
5. 加拿大省级债额外关注：发行量对二级 spread 的供给压力、小省份流动性折价

**风险预警信号（红线）**：
- 一般基金余额/收入 < 5%，或被一次性收入掩盖的经常性赤字
- 净养老金负债/收入 > 200%，且折现率假设显著高于高评级公司债收益率
- 收入债 DSCR < 1.2x，或费率上调连续两年低于通胀
- 省级净债务/GDP 连续上升、依赖短期票据滚动长期资本开支
- 评级机构列入 Negative Watch 或连续下调（美国市政债尤其关注 S&P/Fitch 的
  州信用增强计划状态）

---

### 6.3 基金/资管产品信用分析

**美国货币市场基金（Rule 2a-7）与债券基金穿透分析**：
- 货币基金：WAM ≤ 60 天、WAL ≤ 120 天、≥10% 日流动性资产、≥30% 周流动性资产，
  只可持有最高两档短期评级（或等价未评级）证券；必须看持仓与 sponsor support 历史
- 债券共同基金/ETF：需分别评估利率久期与信用敞口，注意 ETF 折溢价与赎回机制
  （AP 申赎、固收 ETF 的流动性错配）
- 混合型/多资产产品：分别评估权益端（市值波动）与固收端（信用风险）
- FOF：两层嵌套穿透，需评估底层基金持仓与费用

**流动性分析框架**：
```
产品层面流动性 = f(底层资产流动性, 赎回条款, 摊余成本法 vs 市值法)
```
- 摊余成本法：仅货币基金在严格条件下可用，价格稳定但隐藏利差风险
- 市值法：反映真实价值，但波动暴露可能引发赎回潮（2020 年 3 月美国
  IG 债基与市政债基即为典型案例）

**底层信用评估步骤**：
1. 获取债券持仓明细（N-PORT/N-CSR 季报、基金年报）
2. 按评级/行业/市政-公司/加拿大-美国分类
3. 计算加权信用利差与加权久期
4. 识别集中度风险（单券 > 5%为高集中度）
5. 评估流动性梯度（高流动→低流动覆盖度）

---

### 6.4 违约案例分析方法论

**违约类型**：
| 类型 | 特征 | 北美典型案例 |
|------|------|------------|
| 流动性违约 | 资产健康但现金流断裂 | Lehman Brothers（2008）、SVB/First Republic（2023） |
| 技术性违约 | 触发条款（交叉违约/加速到期） | 部分 2015-2016 美国能源高收益发行人 |
| 经营性违约 | 主业恶化导致还款能力下降 | Hertz（2020）、Bed Bath & Beyond（2023） |
| 欺诈性违约 | 财务造假/资产腾挪 | Enron（2001）、WorldCom（2002）、Nortel（加，2009） |
| 市政/主权型 | 财政与养老金失衡 | Detroit（2013）、Puerto Rico COFINA（2017） |

**违约前沿信号（Precursor Signals）**：

```
财务层面：
  - 应收账款/收入 异常增高或账龄快速拉长（渠道压货/虚增收入）
  - 现金余额高但同时全额动用循环信贷（revolver 提款）
  - 商誉/无形资产占比持续增大，减值风险累积
  - 关联方交易占比异常（尤其私有化后的发行人）

市场层面：
  - 二级市场价格持续下跌（跌破 80）
  - 信用利差快速走阔（单周 > 50bp）
  - CDS 报价快速上升，或 CDS 与现券出现大幅负基差
  - 一级市场再融资窗口关闭（新发失败或大幅折价）
  - 主承销商更换或不参与后续发行

评级层面：
  - 评级列入负面观察（Negative Watch）或降级审查
  - 多家评级机构下调（split rating 收敛向下）
  - 展望由稳定下调至负面
```

**事后分析框架（Post-Default Analysis）**：
1. 违约触发时点与资金流向重构
2. 资产负债表"真实性"评估（区分真实资产 vs 账面资产）
3. 债权优先级梳理（担保顺序、抵质押品、担保/母公司结构）
4. 处置预期回收率估算（Recovery Rate）：美国 Chapter 11 流程与加拿大
   CCAA（Companies' Creditors Arrangement Act）流程差异会显著影响回收时间与金额
5. 系统性风险传染路径（交叉持有、同类主体、养老金/保险的下游敞口）

**北美回收率参考**（Moody's 长期研究口径，仅作量级参考）：
- 优先担保银行贷款（first-lien term loan）：约 60%-80%
- 优先无担保公司债（senior unsecured）：约 30%-50%
- 次级债（subordinated）：约 10%-30%
- 美国投资级市政债违约罕见，违约后回收率通常高于公司债（有专项收入或征税权支撑），
  但 Detroit / Puerto Rico 等案例显示养老金与结构性赤字会显著压低回收
- 加拿大公司债违约样本少、回收率历史上高于美国同档（担保结构与银行主导融资），
  不宜直接用美国数据外推

---

## 七、与其他 Skill 的关联

| 相关 Skill | 互补关系 |
|------------|----------|
| `options-advanced` | 可转债的转股期权与含权债嵌入期权定价由 options-advanced 处理，本 skill 负责纯债价值与信用风险 |
| `macro-analysis` | 宏观利率环境（Fed / Bank of Canada）与信用周期判断由 macro skill 提供输入 |
| `risk-analysis` | 组合层面信用风险（VaR/CVaR）参考 risk-analysis skill |
| `edgar-sec-filings` | 美国发行人 10-K/10-Q/8-K 与 XBRL 财务数据提取由 edgar-sec-filings skill 负责 |
| `sec-edgar` | EDGAR 检索与文档定位；加拿大发行人改用 SEDAR+ |
| `yfinance` | 股债价格、信用 ETF、隐含波动率等市场数据获取 |
| `data-routing` | 数据源选择与路由（含加拿大发行人的 SEDAR+ 路径说明） |

---

## 八、快速参考

### 常用公式速查

```
YTM 近似公式：
  YTM ≈ [C + (F-P)/n] / [(F+P)/2]

久期与价格变化：
  ΔP ≈ -D_mod × P × Δy + 0.5 × CX × P × (Δy)²

DV01 = D_mod × P × 0.0001 × 持仓面值

信用利差 = 债券YTM - 同期限 UST（或 GoC）YTM

免税等价收益率（美国市政债）= 免税收益率 / (1 - 边际税率)

Z-Score 风险信号：
  Z > 2.99 → 安全   1.81 < Z < 2.99 → 灰色   Z < 1.81 → 危险

违约距离 DD → EDF：
  DD > 4: EDF < 0.1%
  DD 2-4: EDF 0.1%-1%
  DD 1-2: EDF 1%-5%
  DD < 1: EDF > 5%
```

### 美国/加拿大固收数据源

| 数据类型 | 推荐来源 |
|----------|----------|
| 美国国债收益率曲线 | 美国财政部 daily yield curve、Fed H.15、FRED（DGS 系列） |
| 加拿大国债（GoC）曲线 | Bank of Canada benchmark bond yields、Statistics Canada |
| 公司债行情与成交 | FINRA TRACE、交易所披露、`yfinance` 债券/ETF 报价 |
| 市政债行情与披露 | MSRB EMMA（官方 statement、15c2-12 事件通知）、MMD/ICE 市政曲线 |
| 发行人财务报表 | SEC EDGAR（10-K/10-Q/8-K、XBRL）；加拿大发行人 SEDAR+ |
| 评级报告 | Moody's、S&P Global、Fitch、Morningstar DBRS 官网 |
| 违约与回收率 | Moody's Default & Recovery 研究、S&P 违约研究 |
| CDS / CDX | 做市商报价、ICE 指数数据（部分为付费） |
| ABS/MBS 数据 | Fannie/Freddie 披露、Ginnie Mae、ABS/MBS 发行说明书与 Reg AB II 报表 |
| 加拿大 MBS/covered bond | CMHC（NHA MBS / CMB）、各银行 covered bond 发行文件 |
