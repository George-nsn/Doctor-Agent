<template>
  <div class="doctor-agent-app font-display">
    <!-- 氛围背景光斑 (Atmospheric Ambient Blobs) -->
    <div class="ambient-blobs">
      <div class="blob blob-indigo" style="width: 520px; height: 520px; top: -120px; right: -100px;"></div>
      <div class="blob blob-violet" style="width: 460px; height: 460px; top: 320px; left: -140px;"></div>
      <div class="blob blob-teal" style="width: 380px; height: 380px; bottom: 80px; right: 25%;"></div>
    </div>

    <!-- 顶部导航状态栏 (Corporate Trust Glassmorphism Header) -->
    <header class="app-header">
      <div class="header-container">
        <div class="header-left">
          <div class="logo-mark">
            <span class="logo-emoji">🩺</span>
          </div>
          <div class="header-title">
            <div class="title-row">
              <h1 class="font-display">Doctor <span class="grad-text">Agent</span></h1>
              <span class="enterprise-badge font-display">ENTERPRISE</span>
            </div>
            <span class="sub-title">医疗多 Agent 循证问诊与全链路可观测控制台</span>
          </div>
        </div>

        <div class="header-right">
          <!-- 引擎提供商徽章 -->
          <div class="ent-pill font-display">
            <span class="neu-glow-dot purple"></span>
            <span>模型: <strong class="provider-highlight">{{ currentProviderName }}</strong></span>
          </div>

          <!-- 服务运行健康状态 -->
          <div class="ent-pill font-display" :class="isOnline ? 'pill-online' : 'pill-offline'">
            <span class="neu-glow-dot" :class="isOnline ? 'emerald' : 'rose'"></span>
            <span>{{ isOnline ? '服务在线' : '服务未连接' }}</span>
          </div>

          <!-- 设置按钮 -->
          <button class="ent-nav-btn font-display" @click="showSettingsDialog = true">
            <el-icon><Setting /></el-icon>
            <span>模型与 Key 设置</span>
          </button>

          <!-- 刷新状态 -->
          <button class="ent-icon-btn" :disabled="refreshing" @click="checkHealth" title="刷新服务状态">
            <el-icon :class="{ 'is-loading': refreshing }"><Refresh /></el-icon>
          </button>
        </div>
      </div>
    </header>

    <!-- 工作台三栏主视图 -->
    <main class="app-main">
      <div class="dashboard-grid">
        <!-- 1. 左栏：系统监控、2000-Token 预算优化、安全护栏审查 -->
        <aside class="col-left">
          <LeftSidebar :result="result" :health="healthStatus" />
        </aside>

        <!-- 2. 中栏：患者问诊主诉、画像卡片、多轮引导追问与医生建议 -->
        <section class="col-center">
          <PatientWorkspace
            :loading="loading"
            :guided-questions="result?.guided_questions || []"
            :result="result"
            @submit="handleConsult"
            @reset="handleReset"
          />
        </section>

        <!-- 3. 右栏：风险分级预警、专科专家路由、融合循证证据与时序 Trace -->
        <aside class="col-right">
          <AgentTraceView :result="result" />
        </aside>
      </div>
    </main>

    <!-- 大模型与 Key 设定弹窗 -->
    <LlmSettingsDialog
      v-model="showSettingsDialog"
      @saved="handleSettingsSaved"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from './api.js'
import LeftSidebar from './components/LeftSidebar.vue'
import PatientWorkspace from './components/PatientWorkspace.vue'
import AgentTraceView from './components/AgentTraceView.vue'
import LlmSettingsDialog from './components/LlmSettingsDialog.vue'

const isOnline = ref(false)
const refreshing = ref(false)
const loading = ref(false)
const healthStatus = ref(null)
const settingsData = ref(null)
const result = ref(null)
const showSettingsDialog = ref(false)

const currentProviderName = computed(() => {
  const p = settingsData.value?.primary_provider || 'deepseek'
  const map = {
    deepseek: 'DeepSeek',
    glm: '智谱 GLM',
    openai: 'OpenAI',
    gemini: 'Gemini'
  }
  return map[p] || p.toUpperCase()
})

const checkHealth = async () => {
  refreshing.value = true
  try {
    const data = await api.getHealth()
    healthStatus.value = data
    isOnline.value = true
  } catch (err) {
    isOnline.value = false
    healthStatus.value = null
  } finally {
    refreshing.value = false
  }
}

const loadSettings = async () => {
  try {
    const data = await api.getSettings()
    settingsData.value = data
  } catch (err) {
    // Silently ignore if backend is still starting up
  }
}

const handleSettingsSaved = () => {
  loadSettings()
}

const handleConsult = async (payload) => {
  loading.value = true
  try {
    const data = await api.consult(payload)
    result.value = data
    ElMessage.success('医疗多 Agent 综合问诊分析完成')
  } catch (err) {
    ElMessage.error('问诊评估服务请求失败，请确保后端服务已在 8000 端口启动')
  } finally {
    loading.value = false
  }
}

const handleReset = () => {
  result.value = null
}

onMounted(() => {
  checkHealth()
  loadSettings()
})
</script>

<style scoped>
.doctor-agent-app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--bg);
  position: relative;
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
  box-shadow: 0 1px 3px 0 rgba(15, 23, 42, 0.04);
  padding: 12px 0;
}

.header-container {
  max-width: 1600px;
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.logo-mark {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: var(--grad);
  display: grid;
  place-items: center;
  box-shadow: var(--shadow-btn);
  flex-shrink: 0;
}

.logo-emoji {
  font-size: 22px;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.15));
}

.header-title {
  display: flex;
  flex-direction: column;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-title h1 {
  font-size: 1.25rem;
  font-weight: 800;
  margin: 0;
  color: var(--text-main);
  letter-spacing: -0.02em;
  line-height: 1.2;
}

.enterprise-badge {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  background: #EEF2FF;
  color: var(--primary);
  border: 1px solid #E0E7FF;
  letter-spacing: 0.06em;
}

.sub-title {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-weight: 500;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.provider-highlight {
  color: var(--primary);
  font-weight: 700;
}

.pill-online {
  border-color: #A7F3D0 !important;
  background: #F0FDF4 !important;
  color: #065F46 !important;
}

.pill-offline {
  border-color: #FECACA !important;
  background: #FEF2F2 !important;
  color: #991B1B !important;
}

.ent-nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 10px;
  background: #FFFFFF;
  border: 1px solid var(--border);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-main);
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.ent-nav-btn:hover {
  transform: translateY(-1px);
  border-color: #CBD5E1;
  background: #F8FAFC;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.1);
  color: var(--primary);
}

.ent-nav-btn:active {
  transform: translateY(0);
}

.ent-icon-btn {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: #FFFFFF;
  border: 1px solid var(--border);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  cursor: pointer;
  display: grid;
  place-items: center;
  color: var(--text-muted);
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.ent-icon-btn:hover {
  color: var(--primary);
  border-color: #CBD5E1;
  background: #F8FAFC;
  transform: translateY(-1px);
}

.ent-icon-btn:active {
  transform: translateY(0);
}

.app-main {
  flex: 1;
  max-width: 1600px;
  width: 100%;
  margin: 0 auto;
  padding: 24px 24px 40px;
  position: relative;
  z-index: 1;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 310px minmax(400px, 1fr) 360px;
  gap: 22px;
  align-items: start;
}

@media (max-width: 1100px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}
</style>
