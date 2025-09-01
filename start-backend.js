const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// Determine the correct python executable path based on the OS
const pythonExecutable = process.platform === 'win32'
  ? path.join('venv', 'Scripts', 'python.exe')
  : path.join('venv', 'bin', 'python');

console.log(`[Backend] Attempting to start Python server with: ${pythonExecutable}`);

// Check if the executable exists before trying to run it
if (!fs.existsSync(pythonExecutable)) {
  console.error(`[Backend] ERROR: Python executable not found at '${pythonExecutable}'.`);
  console.error('[Backend] Please ensure you have created the virtual environment by running: python -m venv venv');
  process.exit(1); // Exit with an error code
}

// Spawn the python process, inheriting stdio to see logs/errors in real-time
const backendProcess = spawn(pythonExecutable, ['app.py'], {
  stdio: 'inherit'
});

backendProcess.on('close', (code) => {
  console.log(`[Backend] Server process exited with code ${code}`);
});