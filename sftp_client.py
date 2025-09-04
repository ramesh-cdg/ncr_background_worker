"""
SFTP client and operations module
"""
import paramiko
import os
from stat import S_ISDIR
from typing import Tuple
from config import settings


class SFTPManager:
    """SFTP connection and operations manager"""
    
    @staticmethod
    def get_connection() -> Tuple[paramiko.SFTPClient, paramiko.Transport]:
        """Get SFTP connection"""
        transport = paramiko.Transport((settings.sftp_host, settings.sftp_port))
        transport.connect(username=settings.sftp_username, password=settings.sftp_password)
        return paramiko.SFTPClient.from_transport(transport), transport
    
    @staticmethod
    def folder_exists(sftp: paramiko.SFTPClient, path: str) -> bool:
        """Check if folder exists on SFTP server"""
        try:
            sftp.listdir(path)
            return True
        except IOError:
            return False
    
    @staticmethod
    def delete_remote_folder(sftp: paramiko.SFTPClient, path: str):
        """Delete remote folder recursively"""
        try:
            for item in sftp.listdir_attr(path):
                full_path = f"{path}/{item.filename}"
                if S_ISDIR(item.st_mode):
                    SFTPManager.delete_remote_folder(sftp, full_path)
                else:
                    sftp.remove(full_path)
            sftp.rmdir(path)
        except FileNotFoundError:
            # Folder doesn't exist, which is fine for new jobs
            pass
        except Exception as e:
            print(f"Failed to delete folder {path}: {e}")
    
    @staticmethod
    def check_and_delete_folder(sftp: paramiko.SFTPClient, remote_base_dir: str):
        """Check if folder exists and delete it"""
        if SFTPManager.folder_exists(sftp, remote_base_dir):
            print(f"Deleting existing folder: {remote_base_dir}")
            try:
                SFTPManager.delete_remote_folder(sftp, remote_base_dir)
                print(f"Successfully deleted folder: {remote_base_dir}")
            except Exception as e:
                print(f"Error deleting folder {remote_base_dir}: {e}")
        else:
            print(f"Folder {remote_base_dir} does not exist, skipping deletion")
    
    @staticmethod
    def ensure_remote_dir(sftp: paramiko.SFTPClient, remote_dir: str):
        """Ensure remote directory exists, create if it doesn't"""
        dirs = remote_dir.strip("/").split("/")
        path = ""
        for d in dirs:
            path = os.path.join(path, d)
            try:
                sftp.listdir(path)
            except IOError:
                sftp.mkdir(path)
    
    @staticmethod
    def upload_to_sftp(sftp: paramiko.SFTPClient, local_path: str, remote_path: str):
        """Upload file to SFTP server"""
        dir_path = os.path.dirname(remote_path)
        SFTPManager.ensure_remote_dir(sftp, dir_path)
        sftp.put(local_path, remote_path)
