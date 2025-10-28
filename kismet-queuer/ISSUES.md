# Issues Found in kismet-queuer

## Critical Issues

- [x] **1. Logger Reference Bug** (kismet_to_queue.py:38)
  - The `_load_config()` method tries to use `self.logger.error()` before the logger is initialized
  - The constructor calls `_load_config()` on line 26 but doesn't call `_setup_logging()` until line 28
  - This will cause an `AttributeError` if the config file can't be read
  - **Fixed:** Changed to use `sys.stderr.write()` instead of `self.logger.error()`

- [x] **2. WebSocket Reconnection Fails After Normal Operation** (kismet_to_queue.py:165-203)
  - When the WebSocket connection closes during normal operation (line 165), the code logs a warning but doesn't trigger reconnection
  - The reconnection loop at line 187 only runs once during startup
  - After a connection drop, the service will exit instead of reconnecting
  - **Fixed:** Added explicit handling after normal connection closure to reset reconnection counter, add delay, and continue reconnecting indefinitely

## Security Issues

- [x] **3. Service Runs as Root** (kismet_to_queue.service:12-13)
  - The systemd service runs as root, which is unnecessary and risky
  - Should use a dedicated low-privilege user
  - **Fixed:** Created dedicated system user 'kismet-queuer' with no login shell, updated service to run as this user, and modified install script to create user and set proper permissions

- [ ] **4. Insecure WebSocket Connection** (kismet_to_queue.py:177)
  - Uses unencrypted `ws://` protocol instead of `wss://`
  - Credentials and device data are transmitted in plaintext over the network
  - **Status: Won't Fix** - Connecting to localhost only, unencrypted connection is acceptable

- [x] **5. No Config File Permission Warnings**
  - The config.ini file contains plaintext passwords but there's no documentation warning users to set restrictive permissions (chmod 600)
  - **Fixed:** Install script now automatically sets chmod 600 on config.ini, ensuring only the owner can read/write it

- [x] **6. Hardcoded Paths** (install_service.sh:9, kismet_to_queue.service:14-15,27)
  - All scripts contain the hardcoded path `/home/ansible/cddf-temp/kismet-queuer`
  - Makes the code non-portable and appears to be a temporary development path
  - **Fixed:** Install script now auto-detects its directory using `dirname` and dynamically replaces all paths in the service file during installation using `sed`

- [x] **6a. Service File Template Path Mismatch** (kismet_to_queue.service:14-15,27)
  - Service file template had `/home/ansible/cddf-temp/kismet-queuer` but install script expected `/opt/kismet-queuer` for sed replacement
  - This mismatch would cause the dynamic path replacement to fail
  - **Fixed:** Updated service file template to use standard `/opt/kismet-queuer` path, which matches install script's sed pattern and follows FHS (Filesystem Hierarchy Standard) for third-party applications

## Code Quality Issues

- [x] **7. Blocking RabbitMQ in Async Code**
  - Uses `pika.BlockingConnection` (synchronous) within an async application
  - This blocks the event loop during RabbitMQ operations
  - Should use an async library like `aio-pika`
  - **Fixed:** Replaced pika with aio-pika, converted _connect_rabbitmq(), _publish_to_rabbitmq(), and cleanup() to async methods using aio-pika's async API

- [x] **8. Misleading Return Value** (kismet_to_queue.py:96-108)
  - In `_publish_to_rabbitmq()`, if `self.channel` is None after reconnection fails, the function still returns `True` on line 108 instead of `False`
  - **Fixed:** Added else clause to return False when self.exchange is None, with appropriate error logging

- [x] **9. Missing Config Validation**
  - No validation that required config values exist before using them with `.get()` and `.getint()`
  - Could fail with confusing errors if config is incomplete
  - **Fixed:** Added _validate_config() method that checks for all required config sections and fields, providing clear error messages if anything is missing

- [x] **10. Base64 Import Inside Function** (kismet_to_queue.py:183)
  - The `base64` module is imported inside `_connect_to_kismet()` instead of at the top of the file
  - **Fixed:** Moved base64 import to top of file with other standard library imports

## Documentation/Deployment Issues

- [x] **11. Placeholder GitHub URL** (kismet_to_queue.service:3)
  - Contains placeholder: `https://github.com/your-repo/kismet-queuer`
  - **Fixed:** Removed Documentation line

- [x] **12. No .gitignore**
  - Missing `.gitignore` file means `config.ini` with credentials could be accidentally committed
  - **Fixed:** Added .gitignore

- [x] **13. Systemd Restart Limit**
  - The `StartLimitBurst=3` in 60 seconds means after 3 failures, the service stops trying to restart
  - May not be desired for a long-running service
  - **Fixed:** Increased restart limits to `StartLimitBurst=5` and `StartLimitIntervalSec=300` (5 failures within 5 minutes), providing more resilience for a long-running service. Also updated to use modern systemd parameter name `StartLimitIntervalSec` instead of deprecated `StartLimitInterval`
