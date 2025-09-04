"""
Validation service module
"""
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
        
        headers = {
            "x-bond-api-public-key": settings.validator_api_key
        }
        
        try:
            with open(zip_file_path, "rb") as file:
                files = {
                    "zip_file": file
                }
                response = requests.post(api_url, headers=headers, files=files)
            
            response_json = json.dumps(response.json())
            
            # Save validation response to database
            DatabaseManager.save_validation_response(job_id, response.status_code, response_json)
            
            parsed = json.loads(response_json)
            result_value = parsed["data"][0]["result"]
            
            # Get current NY time
            current_datetime = redis_manager.get_current_ny_time_str()
            
            if result_value == 'Valid' or result_value == 'Warning':
                # Update job_details table for successful validation
                success = DatabaseManager.update_job_details_for_validation(
                    job_id, sku_id, username, campaign, current_datetime, row_id
                )
                
                if success:
                    print("✅ Database updated successfully for valid validation")
                    return True
                else:
                    print("⚠️ No rows updated in job_details")
                    return False
            else:
                # Update job_details table for failed validation
                DatabaseManager.update_job_details_for_failed_validation(
                    job_id, current_datetime, row_id
                )
                print("❌ Database updated for invalid validation")
                return False
                
        except Exception as e:
            print(f"❌ Error in validation or database update: {e}")
            return False
