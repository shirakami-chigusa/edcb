import time
import logging
from zeroconf import ServiceBrowser, Zeroconf
import subprocess
import os

# ロギングの設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 設定値 (環境に合わせて変更してください)
TARGET_SMB_SERVER_HOSTNAME = "あなたのSMBサーバーのBonjour名.local" # 例: MyNAS.local
SMB_SHARE_NAME = "共有フォルダ名" # 例: public
SMB_USERNAME = "SMB接続のユーザー名"

# !!! セキュリティ警告 !!!
# 以下のパスワードをスクリプトに直接記述するのは非常に危険です。
# このスクリプトファイルへのアクセス権限を持つ誰もがパスワードを閲覧できてしまいます。
# 代替案として、環境変数、macOSのキーチェーン、または他のセキュアな認証情報管理方法の使用を強く推奨します。
# 例 (macOSキーチェーン): info.plistやlaunchdで起動する場合、直接のパスワードプロンプトは難しいため、
# キーチェーンからの読み込み (スクリプト内のmountコマンド付近のコメント参照) や、
# 環境変数経由での設定 (例: os.getenv('SMB_PASSWORD')) を検討してください。
SMB_PASSWORD = "SMB接続のパスワード" # <- 危険: ハードコードされたパスワード。運用時には変更してください。

MOUNT_POINT = f"/Volumes/{SMB_SHARE_NAME}"

class SMBServiceListener:
    def __init__(self):
        self.is_mounted = False
        self.mounted_server_name = None

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            discovered_hostname = info.server.rstrip('.local.') + '.local'
            logging.info(f"Discovered service: Name={name}, Type={type}, Host={discovered_hostname}, Addresses={info.parsed_addresses()}")

            if discovered_hostname == TARGET_SMB_SERVER_HOSTNAME:
                logging.info(f"Target SMB server ({TARGET_SMB_SERVER_HOSTNAME}) found.")
                if not self.is_mounted:
                    logging.info(f"Share is not currently mounted. Attempting to mount...")
                    # Ensure addresses are available and select the first one
                    if info.addresses and len(info.addresses) > 0:
                        # mount_smb_share expects bytes for ip_address_bytes, but get_service_info.addresses are already bytes
                        # However, info.parsed_addresses() gives strings. We need to handle this.
                        # The original call was info.addresses[0] which are bytes. Let's stick to that.
                        # info.addresses are raw IPv4address bytes or IPv6address bytes
                        # We need to make sure we are passing the correct format (likely IPv4 bytes for smb)

                        # Find an IPv4 address if possible from info.addresses
                        ipv4_address_bytes = None
                        for addr_bytes in info.addresses:
                            if len(addr_bytes) == 4: # Basic check for IPv4 address bytes
                                ipv4_address_bytes = addr_bytes
                                break

                        if ipv4_address_bytes:
                            if self.mount_smb_share(ipv4_address_bytes, info.port):
                                logging.info(f"Successfully ensured mount for {name} at {MOUNT_POINT}.")
                                self.is_mounted = True
                                self.mounted_server_name = name # Store the Bonjour service name
                            else:
                                logging.error(f"Mounting attempt for {name} failed.")
                        else:
                            logging.warning(f"No suitable IPv4 address found for {name} in {info.addresses}. Cannot attempt mount.")
                    else:
                        logging.warning(f"No addresses found for {TARGET_SMB_SERVER_HOSTNAME}. Cannot attempt mount.")
                else:
                    # If it's already mounted, check if it's by the same service instance.
                    # This can happen if Zeroconf sends multiple add_service events or if the script restarts.
                    if self.mounted_server_name == name:
                        logging.info(f"Target server {name} found, and share is already mounted by this service instance. No action needed.")
                    else:
                        # This case could be complex: share is mounted, but perhaps by a different server name (unlikely for TARGET_SMB_SERVER_HOSTNAME)
                        # or the script restarted and self.mounted_server_name is None.
                        # For simplicity, if it's mounted and matches TARGET_SMB_SERVER_HOSTNAME, we assume it's the correct one.
                        # The mount_smb_share method's "already mounted" check handles this gracefully.
                        logging.info(f"Target server {name} found, but share is already mounted (possibly by a previous session or different instance: {self.mounted_server_name}). Verifying mount...")
                        # We can optionally re-verify or simply trust the existing mount if mount_smb_share confirms it.
                        # For now, let mount_smb_share handle the "already mounted" logic.

                        # Find an IPv4 address if possible from info.addresses
                        ipv4_address_bytes = None
                        for addr_bytes in info.addresses:
                            if len(addr_bytes) == 4: # Basic check for IPv4 address bytes
                                ipv4_address_bytes = addr_bytes
                                break

                        if ipv4_address_bytes:
                            if self.mount_smb_share(ipv4_address_bytes, info.port): # Re-check, it will return True if already mounted
                                 self.is_mounted = True # Ensure state is correct
                                 self.mounted_server_name = name # Update to current service name
                                 logging.info(f"Verified existing mount for {name} at {MOUNT_POINT}.")
                            else:
                                 logging.error(f"Verification of existing mount for {name} indicated an issue, or remount failed.")
                                 # State remains is_mounted = True but with potential issues, or mount_smb_share failed to remount.
                                 # This part might need more robust handling if mount_smb_share can clear a failed mount.
                        else:
                            logging.warning(f"No suitable IPv4 address found for {name} in {info.addresses} during re-verification. Cannot verify mount.")
            # Add logging for non-target services if desired, for now, it's silent.

    def remove_service(self, zeroconf, type, name):
        logging.info(f"Service removed event: Name={name}, Type={type}")

        if name == self.mounted_server_name and self.is_mounted:
            logging.info(f"Target SMB server {self.mounted_server_name} removed from network or no longer broadcasting. Attempting to unmount.")
            if self.unmount_smb_share(): # This method will be implemented next
                logging.info(f"Successfully unmounted {SMB_SHARE_NAME} from {MOUNT_POINT}.")
                self.is_mounted = False
                self.mounted_server_name = None
            else:
                logging.error(f"Failed to unmount {SMB_SHARE_NAME}. It may still be mounted at {MOUNT_POINT}.")
        elif name == self.mounted_server_name and not self.is_mounted:
            # This case should ideally not happen if logic is correct, but good to log
            logging.warning(f"Service {name} removed, which matches tracked server, but state indicates not mounted. No action taken.")
        elif self.is_mounted:
            logging.info(f"Service {name} removed, but it's not the currently mounted server ({self.mounted_server_name}). No action taken.")
        else:
            logging.info(f"Service {name} removed. No shares are currently mounted by this script. No action taken.")

    def update_service(self, zeroconf, type, name):
        # サービス情報が更新されたときの処理（必要であれば）
        pass

    def mount_smb_share(self, ip_address_bytes, port):
        # IPアドレスを整形
        ip_address = ".".join(map(str, ip_address_bytes))

        # マウントポイントが存在しない場合は作成
        os.makedirs(MOUNT_POINT, exist_ok=True)

        # 既にマウントされているかチェック
        try:
            # df -h でマウントされているか確認
            df_output = subprocess.check_output(['df', '-h']).decode('utf-8')
            if MOUNT_POINT in df_output:
                logging.info(f"Share already mounted at {MOUNT_POINT}. Skipping mount.")
                return True # Already mounted is a success state for our purpose
        except Exception as e:
            logging.error(f"Error checking mount status: {e}")
            # Continue to attempt mount even if check fails, but log it.

        logging.info(f"Attempting to mount smb://{ip_address}/{SMB_SHARE_NAME}")

        # mount コマンドの実行
        # パスワードをコマンドラインに直接渡すのはセキュリティリスクがあります。
        # macOSのキーチェーンからパスワードを取得する方が安全です。
        # 例: password = subprocess.check_output(['security', 'find-internet-password', '-s', TARGET_SMB_SERVER_HOSTNAME, '-a', SMB_USERNAME, '-w']).decode('utf-8').strip()

        mount_command = [
            '/sbin/mount', '-t', 'smbfs',
            f'//{SMB_USERNAME}:{SMB_PASSWORD}@{ip_address}/{SMB_SHARE_NAME}',
            MOUNT_POINT
        ]

        try:
            subprocess.run(mount_command, check=True, capture_output=True, text=True)
            logging.info(f"Successfully mounted {SMB_SHARE_NAME} to {MOUNT_POINT}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to mount SMB share. Error: {e.stderr.strip()}")
            return False
        except FileNotFoundError:
            logging.error("/sbin/mount command not found. Ensure it's in your PATH.")
            return False
        except Exception as e:
            logging.error(f"An unexpected error occurred during mount: {e}")
            return False

    def unmount_smb_share(self):
        logging.info(f"Attempting to unmount {MOUNT_POINT}...")

        # Check if MOUNT_POINT is actually mounted first
        try:
            df_output = subprocess.check_output(['df', '-h']).decode('utf-8')
            if MOUNT_POINT not in df_output:
                logging.info(f"{MOUNT_POINT} is not currently mounted. No unmount action needed.")
                # Consider if this should return True as "successfully unmounted" or a different state.
                # For the state machine, if it's not mounted, it's effectively unmounted.
                return True
        except Exception as e:
            logging.error(f"Error checking mount status before unmount: {e}. Proceeding with unmount attempt.")

        # Attempt 1: diskutil unmount (often preferred on macOS)
        unmount_command_diskutil = ['diskutil', 'unmount', MOUNT_POINT]
        try:
            logging.info(f"Trying unmount with: {' '.join(unmount_command_diskutil)}")
            subprocess.run(unmount_command_diskutil, check=True, capture_output=True, text=True)
            logging.info(f"Successfully unmounted {MOUNT_POINT} using diskutil.")
            return True
        except FileNotFoundError:
            logging.warning("`diskutil` command not found. Will try `/sbin/umount`.")
        except subprocess.CalledProcessError as e:
            logging.warning(f"Unmount with `diskutil` failed. Error: {e.stderr.strip()}. Will try `/sbin/umount`.")
        except Exception as e:
            logging.warning(f"An unexpected error occurred with `diskutil unmount`: {e}. Will try `/sbin/umount`.")

        # Attempt 2: /sbin/umount (standard Linux/macOS)
        unmount_command_umount = ['/sbin/umount', MOUNT_POINT]
        try:
            logging.info(f"Trying unmount with: {' '.join(unmount_command_umount)}")
            subprocess.run(unmount_command_umount, check=True, capture_output=True, text=True)
            logging.info(f"Successfully unmounted {MOUNT_POINT} using /sbin/umount.")
            return True
        except FileNotFoundError:
            logging.error("`/sbin/umount` command not found. Unmount failed.")
            return False
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to unmount {MOUNT_POINT} using /sbin/umount. Error: {e.stderr.strip()}")
            return False
        except Exception as e:
            logging.error(f"An unexpected error occurred during /sbin/umount: {e}")
            return False

if __name__ == '__main__':
    logging.info("Starting Bonjour SMB service monitor...")
    zeroconf = Zeroconf()
    listener = SMBServiceListener()
    # SMBサービスタイプ (_smb._tcp) を監視
    browser = ServiceBrowser(zeroconf, "_smb._tcp.local.", listener)

    try:
        # プログラムを永続的に実行し続ける
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Monitor stopped by user.")
    finally:
        zeroconf.close()
        logging.info("Zeroconf resources closed.")
