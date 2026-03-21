import React, { useState, useEffect } from 'react';
import {
  Card,
  Row,
  Col,
  Form,
  Input,
  InputNumber,
  Button,
  Select,
  Progress,
  Table,
  Statistic,
  message,
  Alert,
  Tag,
  Divider,
  Switch,
  Tooltip,
  Badge,
} from 'antd';
import {
  ThunderboltOutlined,
  StopOutlined,
  DownloadOutlined,
  InfoCircleOutlined,
  ExperimentOutlined,
  LineChartOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { optimizeApi, backtestApi } from '../api/client';
import type { OptimizationProgress, BacktestParameters, VersionInfo, OptimizationRequest } from '../types';

const OptimizePage: React.FC = () => {
  const [form] = Form.useForm();
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<OptimizationProgress | null>(null);
  const [result, setResult] = useState<{
    best_params: BacktestParameters;
    best_fitness: number;
    history: any[];
    use_wfo?: boolean;
    avg_oos_fitness?: number;
  } | null>(null);
  const [historyData, setHistoryData] = useState<any[]>([]);
  const [wsRef, setWsRef] = useState<WebSocket | null>(null);
  const [, setVersionInfo] = useState<VersionInfo | null>(null);
  const [isRefactored, setIsRefactored] = useState(false);

  // Check if backend is refactored version
  useEffect(() => {
    const checkVersion = async () => {
      try {
        const info = await backtestApi.getVersionInfo();
        setVersionInfo(info);
        setIsRefactored(info.refactored || false);
      } catch (e) {
        // Fallback to legacy mode
        setIsRefactored(false);
      }
    };
    checkVersion();
  }, []);

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      if (wsRef) {
        wsRef.close();
      }
    };
  }, [wsRef]);

  const startOptimization = async (values: any) => {
    setRunning(true);
    setProgress(null);
    setResult(null);
    setHistoryData([]);

    try {
      // Build request based on mode (refactored vs legacy)
      const request: OptimizationRequest = isRefactored
        ? {
            start_date: values.start_date,
            end_date: values.end_date,
            interval: values.interval || '15m',
            n_trials: values.n_trials,
            min_trades: values.min_trades,
            use_wfo: values.use_wfo,
            n_splits: values.use_wfo ? values.n_splits : 3,
          }
        : {
            start_date: values.start_date,
            end_date: values.end_date,
            interval: values.interval || '15m',
            n_trials: 100, // dummy value for legacy mode
            min_trades: 50,
            use_wfo: false,
            n_splits: 3,
            population_size: values.population_size,
            generations: values.generations,
            crossover_rate: values.crossover_rate,
            mutation_rate: values.mutation_rate,
            objective: values.objective,
          };

      // Start optimization
      const { optimization_id } = await optimizeApi.startOptimization(request);

      // Connect WebSocket
      const ws = optimizeApi.createOptimizationSocket(
        optimization_id,
        request,
        // onProgress
        (data: OptimizationProgress) => {
          setProgress(data);
          setHistoryData((prev) => [...prev, data]);
        },
        // onComplete
        (data: any) => {
          setResult({
            best_params: data.best_params,
            best_fitness: data.best_fitness,
            history: data.history,
            use_wfo: data.use_wfo || values.use_wfo,
          });
          setRunning(false);
          message.success('优化完成！');
        },
        // onError
        (error: string) => {
          message.error(error);
          setRunning(false);
        }
      );

      setWsRef(ws);

      ws.onclose = () => {
        setRunning(false);
      };
    } catch (error: any) {
      message.error(error.message || '启动优化失败');
      setRunning(false);
    }
  };

  const stopOptimization = () => {
    if (wsRef) {
      wsRef.close();
      setWsRef(null);
    }
    setRunning(false);
    message.info('优化已停止');
  };

  const exportResult = () => {
    if (!result) return;

    const exportData = {
      ...result,
      optimizer: isRefactored ? 'Optuna TPE' : 'Genetic Algorithm',
      timestamp: new Date().toISOString(),
    };

    const data = JSON.stringify(exportData, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `optimization_result_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const getProgressChartOption = () => {
    if (historyData.length === 0) return {};

    const isWFO = result?.use_wfo || historyData[0]?.split !== undefined;

    if (isWFO) {
      // WFO progress chart
      const splits = historyData.map((d) => d.split || 0);
      const isFitness = historyData.map((d) => d.is_fitness || 0);
      const oosFitness = historyData.map((d) => d.oos_fitness || 0);

      return {
        title: {
          text: 'Walk-Forward Optimization 进度',
          left: 'center',
        },
        tooltip: { trigger: 'axis' },
        legend: {
          data: ['IS适应度', 'OOS适应度'],
          bottom: 0,
        },
        xAxis: {
          type: 'category',
          data: splits.map((s) => `Split ${s}`),
          name: 'WFO分割',
        },
        yAxis: {
          type: 'value',
          name: '适应度',
        },
        series: [
          {
            name: 'IS适应度',
            type: 'bar',
            data: isFitness,
            itemStyle: { color: '#1890ff' },
          },
          {
            name: 'OOS适应度',
            type: 'bar',
            data: oosFitness,
            itemStyle: { color: '#52c41a' },
          },
        ],
        grid: {
          left: '10%',
          right: '10%',
          bottom: '15%',
        },
      };
    } else {
      // Regular Optuna progress chart
      const trials = historyData.map((d) => d.trial || d.generation || 0);
      const bestValues = historyData.map((d) => d.global_best || d.best_value || 0);
      const currentValues = historyData.map((d) => d.best_fitness || d.value || 0);

      return {
        title: {
          text: 'Optuna TPE 优化进度',
          left: 'center',
        },
        tooltip: { trigger: 'axis' },
        legend: {
          data: ['最佳适应度', '当前Trial'],
          bottom: 0,
        },
        xAxis: {
          type: 'category',
          data: trials,
          name: 'Trial',
        },
        yAxis: {
          type: 'value',
          name: '适应度 (Calmar Ratio)',
        },
        series: [
          {
            name: '最佳适应度',
            type: 'line',
            data: bestValues,
            smooth: true,
            lineStyle: { width: 2, color: '#1890ff' },
          },
          {
            name: '当前Trial',
            type: 'scatter',
            data: currentValues,
            itemStyle: { opacity: 0.5, color: '#52c41a' },
          },
        ],
        grid: {
          left: '10%',
          right: '10%',
          bottom: '15%',
        },
      };
    }
  };

  const paramTableData = result
    ? Object.entries(result.best_params).map(([key, value]) => ({
        key,
        name: key,
        value: value as number,
      }))
    : [];

  const paramColumns = [
    {
      title: '参数名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '最优值',
      dataIndex: 'value',
      key: 'value',
      render: (v: number) => (
        <Tag color="blue">{typeof v === 'number' ? v.toFixed(2) : v}</Tag>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {/* Version Badge */}
      {isRefactored && (
        <Alert
          message={
            <span>
              <Badge status="success" />
              <strong> 重构版本 2.0</strong> - 使用 Optuna TPE 贝叶斯优化 + Calmar比率适应度函数
              <Tooltip title="Tree-structured Parzen Estimator - 比遗传算法更高效">
                <InfoCircleOutlined style={{ marginLeft: 8 }} />
              </Tooltip>
            </span>
          }
          type="success"
          showIcon
          style={{ marginBottom: 24 }}
        />
      )}

      {/* Main Info Alert */}
      <Alert
        message={
          isRefactored ? (
            <span>
              <ExperimentOutlined /> Optuna TPE 贝叶斯优化
            </span>
          ) : (
            <span>
              <ThunderboltOutlined /> 遗传算法优化
            </span>
          )
        }
        description={
          isRefactored
            ? '使用贝叶斯优化自动搜索最优参数。相比遗传算法，TPE利用历史试验信息，收敛更快。优化过程可能需要几分钟，请耐心等待。'
            : '使用遗传算法自动搜索最优参数组合。优化过程可能需要几分钟时间，请耐心等待。'
        }
        type="info"
        showIcon
        style={{ marginBottom: 24 }}
      />

      {/* Refactored Features */}
      {isRefactored && (
        <Card
          title="重构改进"
          size="small"
          style={{ marginBottom: 24 }}
          extra={<Tag color="blue">v2.0</Tag>}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Card size="small" title="Module 1: 漏洞修复">
                <ul style={{ paddingLeft: 16, margin: 0 }}>
                  <li>消除前视偏差</li>
                  <li>动态VWAP止盈</li>
                  <li>ATR自适应止损</li>
                </ul>
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" title="Module 2: 微观结构">
                <ul style={{ paddingLeft: 16, margin: 0 }}>
                  <li>异常波动过滤</li>
                  <li>假突破回踩确认</li>
                  <li>EMA动能验证</li>
                </ul>
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" title="Module 3: 优化算法">
                <ul style={{ paddingLeft: 16, margin: 0 }}>
                  <li>Optuna TPE贝叶斯优化</li>
                  <li>Calmar比率适应度</li>
                  <li>Walk-Forward验证</li>
                </ul>
              </Card>
            </Col>
          </Row>
        </Card>
      )}

      {/* Optimization Config */}
      <Card title="优化配置" style={{ marginBottom: 24 }}>
        <Form
          form={form}
          layout="vertical"
          onFinish={startOptimization}
          initialValues={
            isRefactored
              ? {
                  start_date: '2025-08-01',
                  end_date: '2026-02-28',
                  interval: '15m',
                  n_trials: 100,
                  min_trades: 100,
                  use_wfo: false,
                  n_splits: 3,
                }
              : {
                  start_date: '2025-08-01',
                  end_date: '2026-02-28',
                  interval: '15m',
                  population_size: 50,
                  generations: 100,
                  crossover_rate: 0.8,
                  mutation_rate: 0.1,
                  objective: 'total_return',
                }
          }
        >
          {/* Date Range - Common */}
          <Row gutter={16}>
            <Col xs={12} md={8}>
              <Form.Item name="start_date" label="开始日期">
                <Input placeholder="YYYY-MM-DD" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={8}>
              <Form.Item name="end_date" label="结束日期">
                <Input placeholder="YYYY-MM-DD" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={8}>
              <Form.Item name="interval" label="数据周期">
                <Select
                  options={[
                    { value: '15m', label: '15分钟' },
                    { value: '30m', label: '30分钟' },
                    { value: '1h', label: '1小时' },
                    { value: '1d', label: '日线' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>

          {isRefactored ? (
            // Refactored: Optuna TPE Settings
            <>
              <Row gutter={16}>
                <Col xs={12} md={6}>
                  <Form.Item
                    name="n_trials"
                    label={
                      <Tooltip title="Optuna优化迭代次数，建议100-300">
                        <span>
                          迭代次数 <InfoCircleOutlined />
                        </span>
                      </Tooltip>
                    }
                  >
                    <InputNumber min={10} max={1000} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item
                    name="min_trades"
                    label={
                      <Tooltip title="交易次数低于此值将施加重度惩罚，确保统计显著性">
                        <span>
                          最小交易次数 <InfoCircleOutlined />
                        </span>
                      </Tooltip>
                    }
                  >
                    <InputNumber min={10} max={500} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item name="use_wfo" label="Walk-Forward优化">
                    <Switch
                      checkedChildren="开启"
                      unCheckedChildren="关闭"
                      onChange={(checked) => {
                        form.setFieldsValue({ use_wfo: checked });
                      }}
                    />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item
                    noStyle
                    shouldUpdate={(prev, curr) => prev.use_wfo !== curr.use_wfo}
                  >
                    {({ getFieldValue }) =>
                      getFieldValue('use_wfo') ? (
                        <Form.Item name="n_splits" label="WFO分割数">
                          <InputNumber min={2} max={5} style={{ width: '100%' }} />
                        </Form.Item>
                      ) : null
                    }
                  </Form.Item>
                </Col>
              </Row>

              {/* WFO Explanation */}
              <Form.Item shouldUpdate={(prev, curr) => prev.use_wfo !== curr.use_wfo}>
                {({ getFieldValue }) =>
                  getFieldValue('use_wfo') ? (
                    <Alert
                      message="Walk-Forward Optimization (WFO)"
                      description="将数据分为多个周期，每个周期在样本内(IS)优化、样本外(OOS)验证，有效防止过拟合。推荐用于最终参数确定。"
                      type="warning"
                      showIcon
                      style={{ marginBottom: 16 }}
                    />
                  ) : (
                    <Alert
                      message="Optuna TPE贝叶斯优化"
                      description="使用Tree-structured Parzen Estimator算法，适应度函数为Calmar比率(年化收益/最大回撤)。比遗传算法更高效。"
                      type="info"
                      showIcon
                      style={{ marginBottom: 16 }}
                    />
                  )
                }
              </Form.Item>
            </>
          ) : (
            // Legacy: GA Settings
            <>
              <Row gutter={16}>
                <Col xs={12} md={6}>
                  <Form.Item name="population_size" label="种群大小">
                    <InputNumber min={10} max={200} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item name="generations" label="迭代代数">
                    <InputNumber min={10} max={500} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item name="objective" label="优化目标">
                    <Select
                      options={[
                        { value: 'total_return', label: '总收益率' },
                        { value: 'sharpe_ratio', label: '夏普比率' },
                        { value: 'profit_factor', label: '盈亏比' },
                        { value: 'win_rate', label: '胜率' },
                      ]}
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col xs={12} md={6}>
                  <Form.Item name="crossover_rate" label="交叉概率">
                    <InputNumber min={0.1} max={1} step={0.1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item name="mutation_rate" label="变异概率">
                    <InputNumber min={0.01} max={0.5} step={0.05} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
            </>
          )}

          {/* Action Buttons */}
          <Row gutter={16}>
            <Col>
              <Form.Item>
                {running ? (
                  <Button danger icon={<StopOutlined />} onClick={stopOptimization} size="large">
                    停止优化
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    htmlType="submit"
                    icon={<ThunderboltOutlined />}
                    size="large"
                  >
                    {isRefactored ? '启动 TPE 优化' : '启动遗传算法'}
                  </Button>
                )}
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Card>

      {/* Progress Card */}
      {running && progress && (
        <Card
          title={
            <span>
              <LineChartOutlined /> 优化进度
              {isRefactored && (
                <Tag color="blue" style={{ marginLeft: 8 }}>
                  {result?.use_wfo ? 'Walk-Forward' : 'Optuna TPE'}
                </Tag>
              )}
            </span>
          }
          style={{ marginBottom: 24 }}
        >
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={24}>
              <Progress
                percent={Math.round(
                  ((progress.trial || progress.generation || 0) /
                    (progress.total_trials || progress.total_generations || 1)) *
                    100
                )}
                status="active"
              />
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={12} md={6}>
              <Statistic
                title={isRefactored ? '当前Trial' : '当前代数'}
                value={progress.trial || progress.generation || 0}
                suffix={`/ ${progress.total_trials || progress.total_generations || 0}`}
              />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title={isRefactored ? '当前Calmar' : '当前适应度'}
                value={progress.best_fitness}
                precision={2}
              />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title={isRefactored ? '最佳Calmar' : '全局最佳'}
                value={progress.global_best}
                precision={2}
                valueStyle={{ color: '#52c41a' }}
              />
            </Col>
            {isRefactored && progress.oos_fitness !== undefined && (
              <Col xs={12} md={6}>
                <Statistic
                  title="OOS适应度"
                  value={progress.oos_fitness}
                  precision={2}
                  valueStyle={{ color: '#1890ff' }}
                />
              </Col>
            )}
          </Row>

          {historyData.length > 5 && (
            <div style={{ marginTop: 24 }}>
              <ReactECharts
                option={getProgressChartOption()}
                style={{ height: 300 }}
                notMerge
              />
            </div>
          )}
        </Card>
      )}

      {/* Result Card */}
      {result && (
        <>
          <Card
            title={
              <span>
                <ExperimentOutlined /> 优化结果
                {isRefactored && (
                  <Tag color="green" style={{ marginLeft: 8 }}>
                    Optuna TPE
                  </Tag>
                )}
              </span>
            }
            extra={
              <Button icon={<DownloadOutlined />} onClick={exportResult}>
                导出结果
              </Button>
            }
            style={{ marginBottom: 24 }}
          >
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Statistic
                  title={isRefactored ? '最佳Calmar比率' : '最佳适应度'}
                  value={result.best_fitness}
                  precision={2}
                  valueStyle={{ color: '#52c41a', fontSize: 32 }}
                />
                {isRefactored && (
                  <div style={{ marginTop: 8, color: '#888' }}>
                    Calmar = 年化收益 / 最大回撤
                  </div>
                )}
              </Col>
              {isRefactored && result.avg_oos_fitness !== undefined && (
                <Col xs={24} md={12}>
                  <Statistic
                    title="平均OOS适应度"
                    value={result.avg_oos_fitness}
                    precision={2}
                    valueStyle={{ color: '#1890ff', fontSize: 24 }}
                  />
                </Col>
              )}
            </Row>

            <Divider>最优参数</Divider>

            <Table
              dataSource={paramTableData}
              columns={paramColumns}
              pagination={false}
              size="small"
              rowKey="key"
            />
          </Card>

          <Card title="收敛曲线">
            <ReactECharts
              option={getProgressChartOption()}
              style={{ height: 400 }}
              notMerge
            />
          </Card>
        </>
      )}
    </div>
  );
};

export default OptimizePage;
