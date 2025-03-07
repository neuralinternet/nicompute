import allure
import pytest
from unittest.mock import patch
import torch
import bittensor
from neurons.Miner.pow import check_cuda_availability

# Test class
@allure.epic("CUDA Availability Tests")
@allure.feature("CUDA Functionality")
class TestCudaAvailability:

    @allure.story("Test CUDA availability when CUDA is available")
    @allure.title("Verify CUDA availability with a mock CUDA device")
    @allure.description("This test verifies that the function correctly logs a message when CUDA is available.")
    @patch('torch.cuda.is_available', return_value=True)
    @patch('torch.cuda.device_count', return_value=2)
    @patch('bittensor.logging.info')
    def test_cuda_available(self, mock_logging_info, mock_device_count, mock_cuda_available):
        with allure.step("Call the function to check CUDA availability"):
            check_cuda_availability()

        with allure.step("Verify that the correct log message is generated"):
            mock_logging_info.assert_called_once_with("CUDA is available with 2 CUDA device(s)!")

    @allure.story("Test CUDA availability when CUDA is not available")
    @allure.title("Verify CUDA availability when CUDA is not available")
    @allure.description("This test verifies that the function correctly logs a warning when CUDA is not available.")
    @patch('torch.cuda.is_available', return_value=False)
    @patch('bittensor.logging.warning')
    def test_cuda_not_available(self, mock_logging_warning, mock_cuda_available):
        with allure.step("Call the function to check CUDA availability"):
            check_cuda_availability()

        with allure.step("Verify that the correct warning message is logged"):
            mock_logging_warning.assert_called_once_with(
                "CUDA is not available or not properly configured on this system."
            )