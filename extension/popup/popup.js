const BACKEND_URL = 'http://localhost:8001';

async function loadProfile() {
  const data = await chrome.storage.local.get(['userId', 'profileType', 'readingLevel']);
  if (data.profileType) document.getElementById('profileType').value = data.profileType;
  if (data.readingLevel) document.getElementById('readingLevel').value = data.readingLevel;
  if (data.userId) {
    document.getElementById('status').textContent = `✓ Active — ID: ${data.userId.substring(0, 8)}...`;
  }
}

document.getElementById('saveBtn').addEventListener('click', async () => {
  const profileType = document.getElementById('profileType').value;
  const readingLevel = document.getElementById('readingLevel').value;
  const status = document.getElementById('status');

  status.textContent = 'Creating profile...';

  try {
    const response = await fetch(`${BACKEND_URL}/api/v1/profiles/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tenant_id: 'clearpath-hackathon',
        profile_type: profileType,
        reading_level: readingLevel,
        language: navigator.language.split('-')[0] || 'en'
      })
    });

    const profile = await response.json();

    await chrome.storage.local.set({
      userId: profile.id,
      tenantId: 'clearpath-hackathon',
      profileType: profile.profile_type,
      readingLevel: profile.reading_level
    });

    status.textContent = `✓ Profile saved! Reload the page to apply.`;

    // Reload active tab to apply
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) setTimeout(() => chrome.tabs.reload(tab.id), 1500);

  } catch (error) {
    status.textContent = `✗ Error: ${error.message}. Is backend running?`;
  }
});

loadProfile();
