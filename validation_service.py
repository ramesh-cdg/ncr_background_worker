"""
Validation service module
"""
import os
import requests
import json
from typing import Optional
from config import settings
from database import DatabaseManager
from redis_manager import redis_manager


class ValidationService:
    """Service for handling model validation"""
    
    @staticmethod
    def send_to_validator(
        zip_file_path: str, 
        sku_id: str, 
        job_id: str, 
        username: str, 
        campaign: str, 
        row_id: Optional[int] = None
    ) -> bool:
        """Send file to validator and update database based on result"""
        api_url = f"{settings.validator_api_url}/{sku_id}"
        
        print(f"🔍 [VALIDATOR] Sending validation request...")
        print(f"   - API URL: {api_url}")
        print(f"   - Zip file: {zip_file_path}")
        print(f"   - SKU ID: {sku_id}")
        print(f"   - Job ID: {job_id}")
        print(f"   - Username: {username}")
        print(f"   - Campaign: {campaign}")
        print(f"   - Row ID: {row_id}")
        
        headers = {
            "x-bond-api-public-key": settings.validator_api_key
        }
        
        try:
            # Check if zip file exists and get size
            if not os.path.exists(zip_file_path):
                print(f"❌ [VALIDATOR] Zip file does not exist: {zip_file_path}")
                return False
            
            zip_size = os.path.getsize(zip_file_path)
            print(f"   - Zip file size: {zip_size} bytes")
            
            with open(zip_file_path, "rb") as file:
                files = {
                    "zip_file": file
                }
                print(f"   - Sending POST request to validator...")
                response = requests.post(api_url, headers=headers, files=files)
            
            print(f"   - Response status code: {response.status_code}")
            print(f"   - Response headers: {dict(response.headers)}")
            
            if response.status_code != 200:
                print(f"❌ [VALIDATOR] HTTP error: {response.status_code}")
                print(f"   - Response text: {response.text}")
                
                # Log failed validation request to database
                print(f"🗄️ [VALIDATOR] Logging failed validation request...")
                DatabaseManager.save_validation_failed_request(
                    job_id=job_id,
                    sku_id=sku_id,
                    response=response.text,
                    api_url=api_url,
                    username=username,
                    campaign=campaign,
                    row_id=row_id
                )
                
                return False
            
            response_data = response.json()
            response_json = json.dumps(response_data)
            
            print(f"   - Response data: {response_json}")
            
            # Save validation response to database
            print(f"🗄️ [VALIDATOR] Saving validation response to database...")
            DatabaseManager.save_validation_response(job_id, response.status_code, response_json)
            print(f"   ✅ Validation response saved to database")
            
            parsed = json.loads(response_json)
            result_value = parsed["data"][0]["result"]
            
            print(f"   - Validation result: {result_value}")
            
            # Get current NY time
            current_datetime = redis_manager.get_current_ny_time_str()
            print(f"   - Current datetime: {current_datetime}")
            
            if result_value == 'Valid' or result_value == 'Warning':
                print(f"✅ [VALIDATOR] Validation passed: {result_value}")
                # Update job_details table for successful validation
                success = DatabaseManager.update_job_details_for_validation(
                    job_id, sku_id, username, campaign, current_datetime, row_id
                )
                
                if success:
                    print("✅ [VALIDATOR] Database updated successfully for valid validation")
                    return True
                else:
                    print("⚠️ [VALIDATOR] No rows updated in job_details")
                    return False
            else:
                print(f"❌ [VALIDATOR] Validation failed: {result_value}")
                # Update job_details table for failed validation
                DatabaseManager.update_job_details_for_failed_validation(
                    job_id, current_datetime, row_id
                )
                print("❌ [VALIDATOR] Database updated for invalid validation")
                return False
                
        except Exception as e:
            print(f"❌ [VALIDATOR] Error in validation or database update: {e}")
            print(f"   - Exception type: {type(e).__name__}")
            print(f"   - Exception details: {str(e)}")
            return False
