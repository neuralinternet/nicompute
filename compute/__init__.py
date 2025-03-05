# The MIT License (MIT)
# Copyright © 2023 Rapiiidooo
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import string

# Define the version of the template module.
__version__ = "1.8.3"
__minimal_miner_version__ = "1.8.3"
__minimal_validator_version__ = "1.8.3"

version_split = __version__.split(".")
__version_as_int__ = (100 * int(version_split[0])) + (10 * int(version_split[1])) + (1 * int(version_split[2]))

# General static vars
# Amount staked to be considered as a valid validator
validator_permit_stake = 1.0e4
weights_rate_limit = 100

# Validators static vars
# Time before the specs requests will time out. time unit = seconds
specs_timeout = 60

# Proof of GPU settings
pog_retry_limit = 30
pog_retry_interval = 80  # seconds

# Time before the proof of work requests will time out. time unit = seconds
pow_timeout = 30
# Initial and minimal proof of work difficulty. Needs benchmark and adjustment.
pow_min_difficulty = 7
# Maximal proof of work difficulty, this to ensure a miner can not be rewarded for an unlimited unreasonable difficulty. Needs benchmark and adjustment.
pow_max_difficulty = 12
# Model: BLAKE2b-512($pass.$salt)
pow_default_mode = "610"
pow_default_chars = str(string.ascii_letters + string.digits + "!@#$%^&*()-_+=[]{};:,.<>")

# Miners static vars
miner_priority_specs = 1  # Lowest priority
miner_priority_challenge = 2  # Medium priority
miner_priority_allocate = 3  # The highest priority
miner_hashcat_location = "hashcat"
miner_hashcat_workload_profile = "3"
miner_hashcat_extended_options = "-O"

SUSPECTED_EXPLOITERS_COLDKEYS = []
SUSPECTED_EXPLOITERS_HOTKEYS = [
    "5HZ1ATsziEMDm1iUqNWQatfEDb1JSNf37AiG8s3X4pZzoP3A",
    "5H679r89XawDrMhwKGH1jgWMZQ5eeJ8RM9SvUmwCBkNPvSCL",
    "5FnMHpqYo1MfgFLax6ZTkzCZNrBJRjoWE5hP35QJEGdZU6ft",
    "5H3tiwVEdqy9AkQSLxYaMewwZWDi4PNNGxzKsovRPUuuvALW",
    "5E6oa5hS7a6udd9LUUsbBkvzeiWDCgyA2kGdj6cXMFdjB7mm",
    "5DFaj2o2R4LMZ2zURhqEeFKXvwbBbAPSPP7EdoErYc94ATP1",
    "5H3padRmkFMJqZQA8HRBZUkYY5aKCTQzoR8NwqDfWFdTEtky",
    "5HBqT3dhKWyHEAFDENsSCBJ1ntyRdyEDQWhZo1JKgMSrAhUv",
    "5FAH7UesJRwwLMkVVknW1rsh9MQMUo78d5Qyx3KpFpL5A7LW",
    "5GUJBJmSJtKPbPtUgALn4h34Ydc1tjrNfD1CT4akvcZTz1gE",
    "5E2RkNBMCrdfgpnXHuiC22osAxiw6fSgZ1iEVLqWMXSpSKac",
    "5DaLy2qQRNsmbutQ7Havj49CoZSKksQSRkCLJsiknH8GcsN2",
    "5GNNB5kZfo6F9hqwXvaRfYdTuJPSzrXbtABzwoL499jPNBjt",
    "5GVjcJLQboN5NcQoP4x8oqovjAiEizdscoocWo9HBYYmPdR3",
    "5FswTe5bbs9n1SzaGpzUd6sDfnzdPfWVS2MwDWNbAneeT15k",
    "5F4bqDZkx79hCxmbbsVMuq312EW9hQLvsBzKsAJgcEqpb8L9",
]

TRUSTED_VALIDATORS_HOTKEYS = [
    "5F4tQyWrhfGVcNhoqeiNsR6KjD4wMZ2kfhLj4oHYuyHbZAc3",  # Opentensor Foundation
    "5GKH9FPPnWSUoeeTJp19wVtd84XqFW4pyK2ijV2GsFbhTrP1",  # τaosτaτs & Corcel
    "5HEo565WAy4Dbq3Sv271SAi7syBSofyfhhwRNjFNSM2gP9M2",  # Foundry
    "5HK5tp6t2S59DywmHRWPBVJeJ86T61KjurYqeooqj8sREpeN",  # Bittensor Guru Podcast
    "5EhvL1FVkQPpMjZX4MAADcW42i3xPSF1KiCpuaxTYVr28sux",  # TAO-Validator.com
    "5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v",  # RoundTable21
    "5DvTpiniW9s3APmHRYn8FroUWyfnLtrsid5Mtn5EwMXHN2ed",  # FirstTensor
    "5E4z3h9yVhmQyCFWNbY9BPpwhx4xFiPwq3eeqmBgVF6KULde",  # Tensorplex
    "5F2CsUDVbRbVMXTh9fAzF9GacjVX7UapvRxidrxe7z8BYckQ",  # Rizzo
    "5GmvyePN9aYErXBBhBnxZKGoGk4LKZApE4NkaSzW62CYCYNA",  # Neural Inτerneτ
    "5F27Eqz2PhyMtGMEce898x31DokNqRVxkm5AhDDe6rDGNvoY",  # Love
]
