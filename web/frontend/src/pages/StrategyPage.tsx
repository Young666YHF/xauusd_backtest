import React from 'react';
import { Card, Row, Col, Typography, Table, Divider, Tag, Alert, Statistic } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';

const { Title, Paragraph, Text } = Typography;

// Strategy A parameters - 贝叶斯优化结果 (2025-12至2026-02, 15分钟, 200 trials)
// 优化表现: 收益191.91%, 回撤7.20%, 夏普5.25
const strategyAParams = [
  { name: '布林带周期', value: '13', description: '布林带中轨计算周期 (优化后)' },
  { name: '布林带标准差', value: '1.62', description: '上下轨偏离中轨的标准差倍数' },
  { name: '肯特纳周期', value: '25', description: '肯特纳通道计算周期 (优化前: 15)' },
  { name: 'ATR周期', value: '19', description: 'ATR计算周期 (优化前: 8)' },
  { name: 'RSI超卖阈值', value: '23', description: 'RSI低于此值视为超卖 (优化前: 21)' },
  { name: 'RSI超买阈值', value: '77', description: 'RSI高于此值视为超买 (优化前: 75)' },
  { name: '止损ATR倍数', value: '1.36', description: '止损距离 = ATR × 1.36 (优化前: 2.3, 收紧)' },
  { name: '最大持仓K线', value: '7', description: '最长持仓时间 (优化前: 5)' },
];

// Strategy B parameters - 贝叶斯优化结果
const strategyBParams = [
  { name: '快速EMA周期', value: '17', description: '短期趋势判断 (优化前: 28, 更敏感)' },
  { name: '慢速EMA周期', value: '32', description: '长期趋势判断 (优化前: 64, 更敏感)' },
  { name: '止损ATR倍数', value: '1.69', description: '初始止损距离 (优化前: 2.2, 收紧)' },
  { name: '追踪止损ATR倍数', value: '4.54', description: '追踪止损距离 (优化前: 3.5, 放宽)' },
  { name: '波动率挤压阈值', value: '0.96', description: '布林带/肯特纳通道宽度比 (优化前: 0.8)' },
];

// Module 1 & 2 新增参数
const advancedParams = [
  { name: 'ATR时间止损基础', value: '2.71', description: '时间止损基础K线数' },
  { name: 'ATR时间止损倍数', value: '0.76', description: '时间止损ATR倍数' },
  { name: '波动率过滤周期', value: '14', description: '异常波动检测周期' },
  { name: '波动率过滤倍数', value: '1.79', description: '异常波动ATR倍数' },
  { name: '回踩确认K线', value: '3', description: '假突破回踩确认K线数' },
  { name: 'EMA动能阈值', value: '0.00082', description: '突破动能最小值 (价格比例)' },
];

const paramColumns = [
  {
    title: '参数名称',
    dataIndex: 'name',
    key: 'name',
    width: 150,
  },
  {
    title: '默认值',
    dataIndex: 'value',
    key: 'value',
    width: 100,
  },
  {
    title: '说明',
    dataIndex: 'description',
    key: 'description',
  },
];

const StrategyPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {/* Strategy A */}
      <Card
        title={
          <span>
            <Tag color="blue">策略A</Tag> 均值回归策略
          </span>
        }
        style={{ marginBottom: 24 }}
      >
        <Alert
          message="适用场景"
          description="亚盘时段（北京时间 06:00 - 14:00），市场处于震荡状态，布林带收缩在肯特纳通道内部"
          type="info"
          showIcon
          style={{ marginBottom: 24 }}
        />

        <Row gutter={24}>
          <Col xs={24} md={12}>
            <Title level={5}>做多条件</Title>
            <ul>
              <li><CheckCircleOutlined style={{ color: '#52c41a' }} /> 价格触及布林带下轨（2.5个标准差）</li>
              <li><CheckCircleOutlined style={{ color: '#52c41a' }} /> RSI &lt; 30（超卖）</li>
              <li><CheckCircleOutlined style={{ color: '#52c41a' }} /> 处于亚盘时段</li>
            </ul>
          </Col>
          <Col xs={24} md={12}>
            <Title level={5}>做空条件</Title>
            <ul>
              <li><CloseCircleOutlined style={{ color: '#ff4d4f' }} /> 价格触及布林带上轨（2.5个标准差）</li>
              <li><CloseCircleOutlined style={{ color: '#ff4d4f' }} /> RSI &gt; 70（超买）</li>
              <li><CloseCircleOutlined style={{ color: '#ff4d4f' }} /> 处于亚盘时段</li>
            </ul>
          </Col>
        </Row>

        <Divider>出场规则</Divider>
        <Row gutter={24}>
          <Col span={8}>
            <Card size="small" title="止盈" bordered={false}>
              <Text>价格回归到VWAP</Text>
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" title="止损" bordered={false}>
              <Text>1.5倍ATR距离</Text>
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" title="时间止损" bordered={false}>
              <Text>持仓超过12根K线（约3小时）</Text>
            </Card>
          </Col>
        </Row>

        <Divider>参数设置</Divider>
        <Table
          dataSource={strategyAParams}
          columns={paramColumns}
          pagination={false}
          size="small"
          rowKey="name"
        />
      </Card>

      {/* Strategy B */}
      <Card
        title={
          <span>
            <Tag color="orange">策略B</Tag> 动量突破策略
          </span>
        }
        style={{ marginBottom: 24 }}
      >
        <Alert
          message="适用场景"
          description="欧美盘时段（北京时间 15:00 - 次日02:00），波动率爆发，布林带突破肯特纳通道"
          type="warning"
          showIcon
          style={{ marginBottom: 24 }}
        />

        <Row gutter={24}>
          <Col xs={24} md={12}>
            <Title level={5}>做多条件</Title>
            <ul>
              <li><CheckCircleOutlined style={{ color: '#52c41a' }} /> 价格收盘突破布林带上轨</li>
              <li><CheckCircleOutlined style={{ color: '#52c41a' }} /> 布林带上轨突破肯特纳通道上轨</li>
              <li><CheckCircleOutlined style={{ color: '#52c41a' }} /> EMA(20) &gt; EMA(50) 多头排列</li>
            </ul>
          </Col>
          <Col xs={24} md={12}>
            <Title level={5}>做空条件</Title>
            <ul>
              <li><CloseCircleOutlined style={{ color: '#ff4d4f' }} /> 价格收盘跌破布林带下轨</li>
              <li><CloseCircleOutlined style={{ color: '#ff4d4f' }} /> 布林带下轨跌破肯特纳通道下轨</li>
              <li><CloseCircleOutlined style={{ color: '#ff4d4f' }} /> EMA(20) &lt; EMA(50) 空头排列</li>
            </ul>
          </Col>
        </Row>

        <Divider>出场规则</Divider>
        <Row gutter={24}>
          <Col span={12}>
            <Card size="small" title="初始止损" bordered={false}>
              <Text>入场K线的低点/高点，或1.5倍ATR距离</Text>
            </Card>
          </Col>
          <Col span={12}>
            <Card size="small" title="追踪止损" bordered={false}>
              <Text>最高盈利点回撤2倍ATR</Text>
            </Card>
          </Col>
        </Row>

        <Divider>参数设置</Divider>
        <Table
          dataSource={strategyBParams}
          columns={paramColumns}
          pagination={false}
          size="small"
          rowKey="name"
        />
      </Card>

      {/* Advanced Parameters */}
      <Card
        title={
          <span>
            <Tag color="purple">高级参数</Tag> Module 1 & 2 优化参数
          </span>
        }
        style={{ marginBottom: 24 }}
      >
        <Alert
          message="参数优化来源"
          description="以下参数来自贝叶斯优化 (Optuna TPE, 200 trials)，数据周期 2025-12至2026-02，15分钟K线。优化目标: Calmar比率 (年化收益/最大回撤)"
          type="success"
          showIcon
          style={{ marginBottom: 24 }}
        />

        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic title="总收益率" value={191.91} suffix="%" valueStyle={{ color: '#52c41a' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="最大回撤" value={7.20} suffix="%" valueStyle={{ color: '#1890ff' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="夏普比率" value={5.25} valueStyle={{ color: '#722ed1' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="胜率" value={50.0} suffix="%" />
            </Card>
          </Col>
        </Row>

        <Table
          dataSource={advancedParams}
          columns={paramColumns}
          pagination={false}
          size="small"
          rowKey="name"
        />
      </Card>

      {/* Technical Indicators */}
      <Card title="技术指标说明">
        <Row gutter={[24, 16]}>
          <Col xs={24} md={8}>
            <Title level={5}>布林带 (Bollinger Bands)</Title>
            <Paragraph>
              由中轨（20周期SMA）、上轨（中轨+2.5倍标准差）、下轨（中轨-2.5倍标准差）组成。
              用于判断价格的相对高低位和波动率状态。
            </Paragraph>
          </Col>
          <Col xs={24} md={8}>
            <Title level={5}>肯特纳通道 (Keltner Channel)</Title>
            <Paragraph>
              由中轨（20周期EMA）、上轨（中轨+1.5倍ATR）、下轨（中轨-1.5倍ATR）组成。
              用于判断波动率扩张状态。
            </Paragraph>
          </Col>
          <Col xs={24} md={8}>
            <Title level={5}>ATR (平均真实波幅)</Title>
            <Paragraph>
              衡量市场波动性的指标。用于计算动态止损距离和仓位管理。
            </Paragraph>
          </Col>
          <Col xs={24} md={8}>
            <Title level={5}>RSI (相对强弱指标)</Title>
            <Paragraph>
              衡量价格变动的速度和幅度。RSI &lt; 30为超卖，&gt; 70为超买。
            </Paragraph>
          </Col>
          <Col xs={24} md={8}>
            <Title level={5}>VWAP (成交量加权平均价)</Title>
            <Paragraph>
              当日成交量加权平均价格。均值回归策略中作为止盈目标。
            </Paragraph>
          </Col>
          <Col xs={24} md={8}>
            <Title level={5}>EMA (指数移动平均)</Title>
            <Paragraph>
              对近期价格赋予更高权重的移动平均线。用于判断趋势方向。
            </Paragraph>
          </Col>
        </Row>
      </Card>
    </div>
  );
};

export default StrategyPage;
