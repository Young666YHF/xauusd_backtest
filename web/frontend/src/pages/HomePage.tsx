import React from 'react';
import { Card, Row, Col, Typography, Button, Space } from 'antd';
import { Link } from 'react-router-dom';
import {
  StockOutlined,
  LineChartOutlined,
  ThunderboltOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons';

const { Title, Paragraph, Text } = Typography;

const features = [
  {
    key: 'strategy',
    icon: <StockOutlined style={{ fontSize: 32, color: '#1890ff' }} />,
    title: '双策略系统',
    description: '均值回归策略（策略A）适用于亚盘震荡行情，动量突破策略（策略B）适用于欧美盘趋势行情。',
    link: '/strategy',
    linkText: '查看策略详情',
  },
  {
    key: 'backtest',
    icon: <LineChartOutlined style={{ fontSize: 32, color: '#52c41a' }} />,
    title: '回测分析',
    description: '实时调整参数，快速验证策略效果。支持权益曲线、交易明细、统计指标等多维度分析。',
    link: '/backtest',
    linkText: '开始回测',
  },
  {
    key: 'optimize',
    icon: <ThunderboltOutlined style={{ fontSize: 32, color: '#faad14' }} />,
    title: '参数优化',
    description: '使用 Optuna TPE 贝叶斯优化自动寻优，Calmar比率适应度函数，支持Walk-Forward验证。',
    link: '/optimize',
    linkText: '开始优化',
  },
];

const HomePage: React.FC = () => {
  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {/* Hero Section */}
      <Card style={{ marginBottom: 24, textAlign: 'center' }}>
        <Title level={2}>XAUUSD 黄金量化交易回测系统</Title>
        <Paragraph style={{ fontSize: 16, color: '#666' }}>
          基于15分钟周期的双策略交易系统，针对亚盘和欧美盘不同行情特点设计，
          结合布林带、肯特纳通道、RSI等技术指标，实现稳定的交易信号。
        </Paragraph>
        <Space size="large">
          <Link to="/backtest">
            <Button type="primary" size="large" icon={<LineChartOutlined />}>
              立即回测
            </Button>
          </Link>
          <Link to="/strategy">
            <Button size="large" icon={<StockOutlined />}>
              了解策略
            </Button>
          </Link>
        </Space>
      </Card>

      {/* Features Grid */}
      <Row gutter={[24, 24]}>
        {features.map((feature) => (
          <Col xs={24} md={8} key={feature.key}>
            <Card
              hoverable
              style={{ height: '100%' }}
              bodyStyle={{ display: 'flex', flexDirection: 'column', height: '100%' }}
            >
              <div style={{ marginBottom: 16 }}>{feature.icon}</div>
              <Title level={4} style={{ marginTop: 0 }}>
                {feature.title}
              </Title>
              <Paragraph style={{ flex: 1, color: '#666' }}>
                {feature.description}
              </Paragraph>
              <Link to={feature.link}>
                <Button type="link" style={{ padding: 0 }}>
                  {feature.linkText} <ArrowRightOutlined />
                </Button>
              </Link>
            </Card>
          </Col>
        ))}
      </Row>

      {/* Quick Stats */}
      <Card style={{ marginTop: 24 }} title="系统特点">
        <Row gutter={[24, 16]}>
          <Col xs={12} md={6}>
            <Text type="secondary">数据周期</Text>
            <div style={{ fontSize: 24, fontWeight: 'bold' }}>15分钟</div>
          </Col>
          <Col xs={12} md={6}>
            <Text type="secondary">支持策略</Text>
            <div style={{ fontSize: 24, fontWeight: 'bold' }}>2种</div>
          </Col>
          <Col xs={12} md={6}>
            <Text type="secondary">可调参数</Text>
            <div style={{ fontSize: 24, fontWeight: 'bold' }}>22个</div>
          </Col>
          <Col xs={12} md={6}>
            <Text type="secondary">优化算法</Text>
            <div style={{ fontSize: 24, fontWeight: 'bold', color: '#1890ff' }}>贝叶斯优化</div>
          </Col>
        </Row>
      </Card>
    </div>
  );
};

export default HomePage;
