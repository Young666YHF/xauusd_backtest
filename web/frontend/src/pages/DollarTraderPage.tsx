import React, { useState, useEffect } from 'react';
import {
  Card,
  Row,
  Col,
  Form,
  InputNumber,
  Button,
  Spin,
  message,
  Table,
  Statistic,
  Space,
  Select,
  Modal,
  Input,
  Alert,
  Divider,
  Dropdown,
  Tag,
} from 'antd';
import {
  PlayCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
  DeleteOutlined,
  FolderOutlined,
  LineChartOutlined,
  DollarOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';

const PRESET_STORAGE_KEY = 'dollar_trader_presets';

interface DollarTraderParams {
  sma_short: number;
  sma_medium: number;
  sma_long: number;
  risk_per_trade: number;
}

interface BacktestResult {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  total_return: number;
  avg_pnl: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  long_trades: number;
  short_trades: number;
  signal_exits: number;
  final_capital: number;
}

interface TradeRecord {
  entry_time: string;
  exit_time: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  pnl: number;
  pnl_pct: number;
  bars_held: number;
  exit_reason: string;
}

interface EquityPoint {
  timestamp: string;
  equity: number;
}

interface BacktestResponse {
  success: boolean;
  result: BacktestResult | null;
  equity_curve: EquityPoint[] | null;
  trades: TradeRecord[] | null;
  error: string | null;
}

interface ParameterPreset {
  id: string;
  name: string;
  description: string;
  parameters: DollarTraderParams;
  created_at: string;
}

const DollarTraderPage: React.FC = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [presets, setPresets] = useState<ParameterPreset[]>([]);
  const [presetModalVisible, setPresetModalVisible] = useState(false);
  const [presetName, setPresetName] = useState('');
  const [presetDesc, setPresetDesc] = useState('');
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null);

  useEffect(() => {
    loadDefaultParams();
    loadPresets();
  }, []);

  const loadDefaultParams = async () => {
    try {
      const response = await fetch('/api/dollar-trader/default-params');
      if (response.ok) {
        const data = await response.json();
        form.setFieldsValue({
          parameters: {
            sma_short: data.sma_short,
            sma_medium: data.sma_medium,
            sma_long: data.sma_long,
            risk_per_trade: data.risk_per_trade,
          },
          start_date: '2025-01-01',
          end_date: '2025-10-31',
          initial_capital: 100000,
          contract_size: 100,
          spread_per_lot: 60,
        });
      }
    } catch (error) {
      // 使用默认参数
      form.setFieldsValue({
        parameters: {
          sma_short: 20,
          sma_medium: 50,
          sma_long: 200,
          risk_per_trade: 0.02,
        },
        start_date: '2025-01-01',
        end_date: '2025-10-31',
        initial_capital: 100000,
        contract_size: 100,
        spread_per_lot: 60,
      });
    }
  };

  const loadPresets = async () => {
    try {
      // 从后端加载预设
      const response = await fetch('/api/dollar-trader/presets');
      let serverPresets: ParameterPreset[] = [];
      if (response.ok) {
        const data = await response.json();
        serverPresets = Object.entries(data).map(([name, preset]: [string, any]) => ({
          id: `server_${name}`,
          name: name,
          description: preset.description || '',
          parameters: {
            sma_short: preset.sma_short,
            sma_medium: preset.sma_medium,
            sma_long: preset.sma_long,
            risk_per_trade: preset.risk_per_trade,
          },
          created_at: new Date().toISOString(),
        }));
      }

      // 从本地加载用户预设
      let localPresets: ParameterPreset[] = [];
      try {
        const stored = localStorage.getItem(PRESET_STORAGE_KEY);
        if (stored) {
          localPresets = JSON.parse(stored);
        }
      } catch (e) {
        // 忽略
      }

      setPresets([...serverPresets, ...localPresets]);
    } catch (error) {
      console.error('加载预设失败:', error);
    }
  };

  const saveLocalPresets = (newPresets: ParameterPreset[]) => {
    const localOnly = newPresets.filter(p => !p.id.startsWith('server_'));
    localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(localOnly));
    setPresets(newPresets);
  };

  const handleSavePreset = () => {
    const currentParams = form.getFieldValue('parameters');
    if (!presetName.trim()) {
      message.error('请输入预设名称');
      return;
    }

    const newPreset: ParameterPreset = {
      id: Date.now().toString(),
      name: presetName.trim(),
      description: presetDesc.trim(),
      parameters: currentParams,
      created_at: new Date().toISOString(),
    };

    saveLocalPresets([...presets, newPreset]);
    setPresetModalVisible(false);
    setPresetName('');
    setPresetDesc('');
    message.success('预设保存成功');
  };

  const handleLoadPreset = (preset: ParameterPreset) => {
    form.setFieldsValue({ parameters: preset.parameters });
    setSelectedPresetId(preset.id);
    message.success(`已加载预设: ${preset.name}`);
  };

  const handleDeletePreset = (id: string) => {
    if (id.startsWith('server_')) {
      message.warning('服务端预设不可删除');
      return;
    }

    const stored = localStorage.getItem(PRESET_STORAGE_KEY);
    const localPresets: ParameterPreset[] = stored ? JSON.parse(stored) : [];
    const updated = localPresets.filter(p => p.id !== id);
    localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(updated));

    setPresets(prev => prev.filter(p => p.id !== id));
    if (selectedPresetId === id) {
      setSelectedPresetId(null);
    }
    message.success('预设已删除');
  };

  const runBacktest = async (values: any) => {
    setLoading(true);
    try {
      const response = await fetch('/api/dollar-trader/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sma_short: values.parameters.sma_short,
          sma_medium: values.parameters.sma_medium,
          sma_long: values.parameters.sma_long,
          risk_per_trade: values.parameters.risk_per_trade,
          start_date: values.start_date,
          end_date: values.end_date,
          initial_capital: values.initial_capital,
          contract_size: values.contract_size,
          spread_per_lot: values.spread_per_lot,
        }),
      });

      const data: BacktestResponse = await response.json();
      setResult(data);

      if (data.success) {
        message.success('回测完成');
      } else {
        message.error(data.error || '回测失败');
      }
    } catch (error: any) {
      message.error(error.message || '回测请求失败');
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    loadDefaultParams();
    setResult(null);
    setSelectedPresetId(null);
  };

  const getEquityChartOption = () => {
    if (!result?.equity_curve) return {};

    const data = result.equity_curve.map((point) => [
      point.timestamp,
      point.equity,
    ]);

    return {
      title: {
        text: '权益曲线',
        left: 'center',
      },
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          const point = params[0];
          return `${point.axisValue}<br/>权益: $${point.value[1].toLocaleString()}`;
        },
      },
      xAxis: {
        type: 'time',
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          formatter: (value: number) => `$${(value / 1000).toFixed(0)}K`,
        },
      },
      series: [
        {
          type: 'line',
          data: data,
          smooth: true,
          lineStyle: { width: 2 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(24, 144, 255, 0.3)' },
                { offset: 1, color: 'rgba(24, 144, 255, 0.05)' },
              ],
            },
          },
        },
      ],
      grid: {
        left: '10%',
        right: '10%',
        bottom: '15%',
      },
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { type: 'slider', start: 0, end: 100 },
      ],
    };
  };

  const tradeColumns = [
    {
      title: '入场时间',
      dataIndex: 'entry_time',
      key: 'entry_time',
      width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '出场时间',
      dataIndex: 'exit_time',
      key: 'exit_time',
      width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '方向',
      dataIndex: 'direction',
      key: 'direction',
      width: 80,
      render: (v: string) => (
        <Tag color={v === 'LONG' ? 'green' : 'red'}>
          {v === 'LONG' ? '做多' : '做空'}
        </Tag>
      ),
    },
    {
      title: '入场价',
      dataIndex: 'entry_price',
      key: 'entry_price',
      width: 100,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '出场价',
      dataIndex: 'exit_price',
      key: 'exit_price',
      width: 100,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '盈亏($)',
      dataIndex: 'pnl',
      key: 'pnl',
      width: 100,
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: 'bold' }}>
          {v >= 0 ? '+' : ''}{v.toFixed(2)}
        </span>
      ),
    },
    {
      title: '盈亏%',
      dataIndex: 'pnl_pct',
      key: 'pnl_pct',
      width: 80,
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f' }}>
          {v >= 0 ? '+' : ''}{v.toFixed(2)}%
        </span>
      ),
    },
    {
      title: '持仓K线',
      dataIndex: 'bars_held',
      key: 'bars_held',
      width: 80,
    },
    {
      title: '出场原因',
      dataIndex: 'exit_reason',
      key: 'exit_reason',
      width: 120,
    },
  ];

  const renderStatsCards = (stats: BacktestResult) => (
    <Row gutter={[16, 16]}>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="总收益率"
            value={stats.total_return}
            precision={2}
            suffix="%"
            valueStyle={{ color: stats.total_return >= 0 ? '#52c41a' : '#ff4d4f' }}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="总交易次数"
            value={stats.total_trades}
            suffix={`次 (胜率 ${stats.win_rate.toFixed(1)}%)`}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="最大回撤"
            value={stats.max_drawdown_pct}
            precision={2}
            suffix="%"
            valueStyle={{ color: '#ff4d4f' }}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic title="夏普比率" value={stats.sharpe_ratio} precision={2} />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="总盈亏"
            value={stats.total_pnl}
            precision={2}
            prefix="$"
            valueStyle={{ color: stats.total_pnl >= 0 ? '#52c41a' : '#ff4d4f' }}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic title="盈亏比" value={stats.profit_factor} precision={2} />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="做多/做空"
            value={`${stats.long_trades}/${stats.short_trades}`}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="卡尔马比率"
            value={stats.calmar_ratio}
            precision={2}
          />
        </Card>
      </Col>
    </Row>
  );

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <Card
        title={
          <Space>
            <DollarOutlined style={{ color: '#52c41a' }} />
            <span>美元策略回测 - 三线SMA趋势跟踪</span>
          </Space>
        }
        style={{ marginBottom: 24 }}
      >
        <Alert
          message="策略说明"
          description="基于SMA_20、SMA_50、SMA_200的经典趋势跟踪策略。多头排列(C>SMA20>SMA50>SMA200)做多，空头排列(C<SMA20<SMA50<SMA200)做空。SMA_20与SMA_50交叉作为出场信号。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />

        <Form form={form} layout="vertical" onFinish={runBacktest}>
          <Row gutter={16}>
            <Col xs={12} md={3}>
              <Form.Item name="start_date" label="开始日期">
                <Input placeholder="YYYY-MM-DD" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="end_date" label="结束日期">
                <Input placeholder="YYYY-MM-DD" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="initial_capital" label="初始资金">
                <InputNumber min={10000} step={10000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="contract_size" label="合约大小">
                <InputNumber min={1} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="spread_per_lot" label="每手点差($)">
                <InputNumber min={0} step={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={6}>
              <Form.Item label=" ">
                <Space>
                  <Dropdown
                    menu={{
                      items: presets.map(p => ({
                        key: p.id,
                        label: (
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>{p.name}</span>
                            {!p.id.startsWith('server_') && (
                              <Button
                                type="text"
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeletePreset(p.id);
                                }}
                              />
                            )}
                          </div>
                        ),
                      })),
                      onClick: ({ key }) => {
                        const preset = presets.find(p => p.id === key);
                        if (preset) handleLoadPreset(preset);
                      },
                    }}
                  >
                    <Button icon={<FolderOutlined />}>
                      加载预设
                    </Button>
                  </Dropdown>
                  <Button icon={<SaveOutlined />} onClick={() => setPresetModalVisible(true)}>
                    保存预设
                  </Button>
                </Space>
              </Form.Item>
            </Col>
          </Row>

          <Divider style={{ margin: '12px 0' }} />

          <Card size="small" title="策略参数" style={{ marginBottom: 16 }}>
            <Row gutter={16}>
              <Col xs={12} md={6}>
                <Form.Item
                  name={['parameters', 'sma_short']}
                  label="短期SMA"
                  rules={[{ required: true }]}
                >
                  <InputNumber min={5} max={100} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={12} md={6}>
                <Form.Item
                  name={['parameters', 'sma_medium']}
                  label="中期SMA"
                  rules={[{ required: true }]}
                >
                  <InputNumber min={10} max={200} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={12} md={6}>
                <Form.Item
                  name={['parameters', 'sma_long']}
                  label="长期SMA"
                  rules={[{ required: true }]}
                >
                  <InputNumber min={50} max={500} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={12} md={6}>
                <Form.Item
                  name={['parameters', 'risk_per_trade']}
                  label="单笔风险(%)"
                  rules={[{ required: true }]}
                >
                  <InputNumber
                    min={0.001}
                    max={0.1}
                    step={0.001}
                    formatter={(value) => `${(Number(value) * 100).toFixed(1)}%`}
                    parser={(value) => Number(value?.replace('%', '')) / 100}
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
            </Row>
          </Card>

          <Row>
            <Col span={24} style={{ textAlign: 'center' }}>
              <Space>
                <Button type="primary" htmlType="submit" icon={<PlayCircleOutlined />} loading={loading} size="large">
                  运行回测
                </Button>
                <Button icon={<ReloadOutlined />} onClick={resetForm} size="large">
                  重置
                </Button>
              </Space>
            </Col>
          </Row>
        </Form>
      </Card>

      {loading && (
        <Card style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" tip="正在运行回测..." />
        </Card>
      )}

      {result?.success && result.result && (
        <>
          <Card title="回测结果" style={{ marginBottom: 24 }}>
            {renderStatsCards(result.result)}
          </Card>

          <Card title="权益曲线" style={{ marginBottom: 24 }}>
            <ReactECharts option={getEquityChartOption()} style={{ height: 400 }} notMerge />
          </Card>

          <Card title="交易记录">
            <Table
              dataSource={result.trades || []}
              columns={tradeColumns}
              rowKey={(record) => record.entry_time + record.direction}
              scroll={{ x: 1000 }}
              pagination={{ pageSize: 20 }}
              size="small"
            />
          </Card>
        </>
      )}

      <Modal
        title="保存参数预设"
        open={presetModalVisible}
        onOk={handleSavePreset}
        onCancel={() => setPresetModalVisible(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form layout="vertical">
          <Form.Item label="预设名称" required>
            <Input
              value={presetName}
              onChange={(e) => setPresetName(e.target.value)}
              placeholder="例如: 保守型SMA"
            />
          </Form.Item>
          <Form.Item label="描述">
            <Input.TextArea
              value={presetDesc}
              onChange={(e) => setPresetDesc(e.target.value)}
              placeholder="可选：描述这个参数组合的特点"
              rows={2}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default DollarTraderPage;
