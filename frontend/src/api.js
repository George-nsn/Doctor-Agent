import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json'
  }
})

export const api = {
  async getHealth() {
    const res = await client.get('/health')
    return res.data
  },

  async consult(payload) {
    const res = await client.post('/consult', payload)
    return res.data
  },

  async reindex(knowledgePath = null) {
    const res = await client.post('/knowledge/reindex', {
      knowledge_path: knowledgePath
    })
    return res.data
  },

  async getSettings() {
    const res = await client.get('/settings')
    return res.data
  },

  async updateSettings(payload) {
    const res = await client.post('/settings', payload)
    return res.data
  },

  async listPatients(userId = 'web-user') {
    const res = await client.get('/patients', { params: { user_id: userId } })
    return res.data
  },

  async getMemory(userId = 'web-user', patientId = 'default-patient') {
    const res = await client.get('/memory', { params: { user_id: userId, patient_id: patientId } })
    return res.data
  },

  async purgeMemory(payload) {
    const res = await client.post('/memory/purge', payload)
    return res.data
  },

  async switchPatient(payload) {
    const res = await client.post('/patients/switch', payload)
    return res.data
  },

  async extractAndSyncMemory(payload) {
    const res = await client.post('/memory/extract_and_sync', payload)
    return res.data
  },

  async listConfirmations(userId = 'web-user', patientId = 'default-patient') {
    const res = await client.get('/memory/confirmations', {
      params: { user_id: userId, patient_id: patientId }
    })
    return res.data
  },

  async resolveConfirmation(payload) {
    const res = await client.post('/memory/confirm_update', payload)
    return res.data
  }
}

export default api
