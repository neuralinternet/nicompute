import allure
import pytest
from unittest.mock import patch, call
import datetime
import subprocess
import os

from neurons.Miner.schedule import start

@allure.epic("Scheduler Tests")
@allure.feature("Scheduler Functionality")
class TestScheduler:

    @allure.story("Test start function with no existing jobs")
    @allure.title("Verify start function schedules a new job correctly")
    @allure.description("This test verifies that the start function schedules a new job correctly when no existing jobs are present.")
    @patch('subprocess.check_output')
    @patch('subprocess.run')
    def test_start_function(self, mock_run, mock_check_output):
        with allure.step("Mock the current datetime"):
            mock_now = datetime.datetime(2023, 10, 1, 12, 0)
            with patch('datetime.datetime') as mock_datetime:
                mock_datetime.now.return_value = mock_now

                with allure.step("Mock the output of 'atq' (no jobs scheduled)"):
                    mock_check_output.return_value = ""

                with allure.step("Call the start function with a delay of 2 days"):
                    start(2)

                with allure.step("Calculate the expected future datetime"):
                    expected_future_datetime = mock_now + datetime.timedelta(days=2)
                    formatted_time = expected_future_datetime.strftime("%H:%M %m/%d/%Y")

                with allure.step("Verify 'atq' was called to list jobs"):
                    mock_check_output.assert_called_once_with(["atq"], text=True)

                with allure.step("Verify 'atrm' was not called and 'at' was called with the correct parameters"):
                    mock_run.assert_has_calls([
                        call(["at", formatted_time], input="./neurons/Miner/kill_container\n", text=True, check=True)
                    ])

    @allure.story("Test start function with existing jobs")
    @allure.title("Verify start function removes existing jobs and schedules a new one")
    @allure.description("This test verifies that the start function removes existing jobs and schedules a new one correctly.")
    @patch('subprocess.check_output')
    @patch('subprocess.run')
    def test_start_function_with_existing_jobs(self, mock_run, mock_check_output):
        with allure.step("Mock the current datetime"):
            mock_now = datetime.datetime(2023, 10, 1, 12, 0)
            with patch('datetime.datetime') as mock_datetime:
                mock_datetime.now.return_value = mock_now

                with allure.step("Mock the output of 'atq' (one job scheduled)"):
                    mock_check_output.return_value = "1 2023-10-02 12:00"

                with allure.step("Call the start function with a delay of 2 days"):
                    start(2)

                with allure.step("Calculate the expected future datetime"):
                    expected_future_datetime = mock_now + datetime.timedelta(days=2)
                    formatted_time = expected_future_datetime.strftime("%H:%M %m/%d/%Y")

                with allure.step("Verify 'atq' was called to list jobs"):
                    mock_check_output.assert_called_once_with(["atq"], text=True)

                with allure.step("Verify 'atrm' was called to remove the existing job and 'at' was called with the correct parameters"):
                    mock_run.assert_has_calls([
                        call(["atrm", "1"], check=True),
                        call(["at", formatted_time], input="./neurons/Miner/kill_container\n", text=True, check=True)
                    ])