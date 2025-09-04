"""
File processing utilities module
"""
import os
import re
import boto3
import requests
import zipfile
import shutil
from urllib.parse import urlparse
from collections import defaultdict
from typing import Dict, List, Tuple
from config import settings


class FileProcessor:
    """File processing utilities"""
    
    @staticmethod
    def generate_presigned_url(file_path: str, expires_in: int = 3600) -> str:
        """Generate presigned URL for Wasabi S3"""
        s3 = boto3.client(
            's3',
            endpoint_url=settings.wasabi_endpoint,
            aws_access_key_id=settings.wasabi_access_key,
            aws_secret_access_key=settings.wasabi_secret_key
        )
        
        return s3.generate_presigned_url('get_object', {
            'Bucket': settings.bucket_name,
            'Key': file_path
        }, ExpiresIn=expires_in)
    
    @staticmethod
    def download_from_wasabi(url: str) -> str:
        """Download file from Wasabi using presigned URL"""
        filename = os.path.basename(urlparse(url).path)
        local_path = f"/tmp/{filename}"
        response = requests.get(url, stream=True)
        if response.status_code != 200:
            raise Exception(f"Failed to download file: HTTP {response.status_code}")
        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return local_path
    
    @staticmethod
    def download_and_prepare(path: str, table_path: str, local_base_dir: str) -> str:
        """Download file from Wasabi and prepare it in local directory"""
        url = FileProcessor.generate_presigned_url(table_path)
        
        try:
            local_path = FileProcessor.download_from_wasabi(url)
            rel_path = os.path.join(path.lstrip("/"))
            final_local_path = os.path.join(local_base_dir, rel_path)
            os.makedirs(os.path.dirname(final_local_path), exist_ok=True)
            shutil.move(local_path, final_local_path)
            return final_local_path
        except Exception as e:
            print(f"Error downloading {table_path}: {e}")
            return None
    
    @staticmethod
    def zip_files(zip_path: str, source_dir: str):
        """Create zip file from source directory"""
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    abs_file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_file_path, source_dir)
                    zipf.write(abs_file_path, rel_path)
    
    @staticmethod
    def clean_structure(file_paths: List[str], model_id: str) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
        """Clean and organize file structure"""
        main_model_glb = 0
        material_model_glb = 0
        mat_id = 0
        material_groups = defaultdict(dict)
        model_outputs = {}
        
        uuid_pattern = r'([0-9a-fA-F\-]{36})'
        
        for path in file_paths:
            filename = os.path.basename(path)
            parent_folder = os.path.basename(os.path.dirname(path))
            parent_folder = parent_folder.lower()
            
            if filename.endswith('.blend'):
                match = re.search(uuid_pattern, filename)
                if match:
                    model_outputs[path] = f"/{model_id}/sources/{model_id}.blend"
            
            elif filename.endswith('.glb') and 'GLB_files' in path:
                if model_id:
                    model_outputs[path] = f"/{model_id}/{model_id}.glb"
                    main_model_glb = 1
            
            elif filename.endswith('.glb') and '/Materials/' in path:
                match = re.search(uuid_pattern, filename)
                if match and model_id:
                    model_outputs[path] = f"/{model_id}/materials/{mat_id}.glb"
                    material_model_glb = 1
            
            elif filename.endswith('.glb') and f"/{model_id}/" in path or filename.endswith('.glb') and f"/{model_id}.glb" in path:
                match = re.search(uuid_pattern, filename)
                if match and model_id:
                    if main_model_glb == 0:
                        model_outputs[path] = f"/{model_id}/{model_id}.glb"
                    if material_model_glb == 0:
                        model_outputs[path] = f"/{model_id}/materials/{mat_id}.glb"
            
            elif filename.endswith(('.fbx', '.obj', '.gltf', '.bin')):
                match = re.search(uuid_pattern, filename)
                model_outputs[f"{path}"] = f"/{model_id}/{parent_folder}/{filename}"
            
            else:
                # pattern = rf"({uuid_pattern})(?:\.\d{{3}})?(?:_[A-Za-z]+)*\.(png|jpg|jpeg|tga|psd)$"
                pattern = rf"({uuid_pattern})(?:\.\d{{3}})?(?:_[A-Za-z]+(?:-[A-Za-z0-9]+)*)*\.(png|jpg|jpeg|tga|psd)$"
                match = re.search(pattern, filename, re.IGNORECASE)
                if match and model_id:
                    if mat_id == 0:
                        mat_id = match.group(1)
                
                if 'material/sources/' in path.lower() or 'materials/sources/' in path.lower():
                    material_groups[mat_id][path] = f"/{model_id}/materials/sources/{filename}"
                elif 'materials/' in path.lower() or 'material/' in path.lower():
                    material_groups[mat_id][path] = f"/{model_id}/materials/{filename}"
                elif 'sources/' in path.lower():
                    material_groups[mat_id][path] = f"/{model_id}/sources/{filename}"
                else:
                    material_groups[mat_id][path] = f"/{model_id}/{parent_folder}/{filename}"
        
        return model_outputs, material_groups
    
    @staticmethod
    def cleanup_files(file_paths: List[str], zip_path: str = None, download_dir: str = None):
        """Clean up temporary files"""
        # Clean up individual files
        for local_path in file_paths:
            try:
                if os.path.exists(local_path):
                    os.remove(local_path)
            except Exception as e:
                print(f"Error deleting {local_path}: {e}")
        
        # Clean up zip file
        if zip_path and os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception as e:
                print(f"Error deleting {zip_path}: {e}")
        
        # Clean up download directory
        if download_dir and os.path.exists(download_dir):
            try:
                shutil.rmtree(download_dir)
            except Exception as e:
                print(f"Error deleting {download_dir}: {e}")
