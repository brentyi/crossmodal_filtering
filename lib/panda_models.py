import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from fannypack.nn import resblocks

from . import dpf


class PandaParticleFilterNetwork(dpf.ParticleFilterNetwork):
    def __init__(self, dynamics_model, measurement_model, **kwargs):
        super().__init__(dynamics_model, measurement_model, **kwargs)


class PandaSimpleDynamicsModel(dpf.DynamicsModel):

    # (x, y, cos theta, sin theta, mass, friction)
    default_state_noise_stddev = (
        0.05,  # x
        0.05,  # y
        # 1e-10,  # cos theta
        # 1e-10,  # sin theta
        # 1e-10,  # mass
        # 1e-10,  # friction
    )

    def __init__(self, state_noise_stddev=None):
        super().__init__()

        if state_noise_stddev is not None:
            self.state_noise_stddev = state_noise_stddev
        else:
            self.state_noise_stddev = self.default_state_noise_stddev

    def forward(self, states_prev, controls, noisy=False):
        # states_prev:  (N, M, state_dim)
        # controls: (N, control_dim)

        assert len(states_prev.shape) == 3  # (N, M, state_dim)

        # N := distinct trajectory count
        # M := particle count
        N, M, state_dim = states_prev.shape
        assert state_dim == len(self.state_noise_stddev)

        states_new = states_prev

        # Add noise if desired
        if noisy:
            dist = torch.distributions.Normal(
                torch.tensor([0.]), torch.tensor(self.state_noise_stddev))
            noise = dist.sample((N, M)).to(states_new.device)
            assert noise.shape == (N, M, state_dim)
            states_new = states_new + noise

            # Project to valid cosine/sine space
            scale = torch.norm(states_new[:, :, 2:4], keepdim=True)
            states_new[:, :, 2:4] /= scale

        # Return (N, M, state_dim)
        return states_new


class PandaDynamicsModel(dpf.DynamicsModel):

    # (x, y, cos theta, sin theta, mass, friction)
    default_state_noise_stddev = (
        0.05,  # x
        0.05,  # y
        # 1e-10,  # cos theta
        # 1e-10,  # sin theta
        # 1e-10,  # mass
        # 1e-10,  # friction
    )

    def __init__(self, state_noise_stddev=None, units=32):
        super().__init__()

        state_dim = 2
        control_dim = 7

        if state_noise_stddev is not None:
            self.state_noise_stddev = state_noise_stddev
        else:
            self.state_noise_stddev = self.default_state_noise_stddev

        self.state_layers = nn.Sequential(
            nn.Linear(state_dim, units // 2),
            resblocks.Linear(units // 2),
        )
        self.control_layers = nn.Sequential(
            nn.Linear(control_dim, units // 2),
            resblocks.Linear(units // 2),
        )
        self.shared_layers = nn.Sequential(
            resblocks.Linear(units),
            resblocks.Linear(units),
            resblocks.Linear(units),
            nn.Linear(units, state_dim),
        )

        self.units = units

    def forward(self, states_prev, controls, noisy=False):
        # states_prev:  (N, M, state_dim)
        # controls: (N, control_dim)

        assert len(states_prev.shape) == 3  # (N, M, state_dim)
        assert len(controls.shape) == 2  # (N, control_dim,)

        # N := distinct trajectory count
        # M := particle count
        N, M, state_dim = states_prev.shape

        # (N, control_dim) => (N, units // 2)
        control_features = self.control_layers(controls)
        assert control_features.shape == (N, self.units // 2)

        # (N, units // 2) => (N, M, units // 2)
        control_features = control_features[:, np.newaxis, :].expand(
            N, M, self.units // 2)
        assert control_features.shape == (N, M, self.units // 2)

        # (N, M, state_dim) => (N, M, units // 2)
        state_features = self.state_layers(states_prev)
        assert state_features.shape == (N, M, self.units // 2)

        # (N, M, units)
        merged_features = torch.cat(
            (control_features, state_features),
            dim=2)
        assert merged_features.shape == (N, M, self.units)

        # (N, M, units * 2) => (N, M, state_dim)
        state_update = self.shared_layers(merged_features)
        assert state_update.shape == (N, M, state_dim)

        # Compute new states
        states_new = states_prev + state_update
        assert states_new.shape == (N, M, state_dim)

        # Add noise if desired
        if noisy:
            # TODO: implement version w/ learnable noise
            # (via reparemeterization; should be simple)
            dist = torch.distributions.Normal(
                torch.tensor([0.]), torch.tensor(self.state_noise_stddev))
            noise = dist.sample((N, M)).to(states_new.device)
            assert noise.shape == (N, M, state_dim)
            states_new = states_new + noise

        # Return (N, M, state_dim)
        return states_new


class PandaMeasurementModel(dpf.MeasurementModel):

    def __init__(self, units=32):
        super().__init__()

        obs_pos_dim = 3
        obs_sensors_dim = 7
        state_dim = 2

        self.observation_image_layers = nn.Sequential(
            nn.Conv2d(in_channels=1, out_channels=3, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            resblocks.Conv2d(channels=3),
            nn.Conv2d(in_channels=3, out_channels=1, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Flatten(),  # 32 * 32 = 1024
            nn.Linear(1024, units),
            nn.ReLU(inplace=True),
            resblocks.Linear(units),
        )
        self.observation_pos_layers = nn.Sequential(
            nn.Linear(obs_pos_dim, units),
            resblocks.Linear(units),
        )
        self.observation_sensors_layers = nn.Sequential(
            nn.Linear(obs_sensors_dim, units),
            resblocks.Linear(units),
        )
        self.state_layers = nn.Sequential(
            nn.Linear(state_dim, units),
        )

        self.shared_layers = nn.Sequential(
            nn.Linear(units * 4, units),
            nn.ReLU(inplace=True),
            resblocks.Linear(units),
            resblocks.Linear(units),
            nn.Linear(units, 1),
            # nn.LogSigmoid()
        )

        self.units = units

    def forward(self, observations, states):
        assert type(observations) == dict
        assert len(states.shape) == 3  # (N, M, state_dim)

        # N := distinct trajectory count
        # M := particle count

        N, M, _ = states.shape

        # Construct observations feature vector
        # (N, obs_dim)
        observation_features = torch.cat((
            self.observation_image_layers(
                observations['image'][:, np.newaxis, :, :]),
            self.observation_pos_layers(observations['gripper_pos']),
            self.observation_sensors_layers(
                observations['gripper_sensors']),
        ), dim=1)

        # (N, obs_dim) => (N, M, obs_dim)
        observation_features = observation_features[:, np.newaxis, :].expand(
            N, M, self.units * 3)
        assert observation_features.shape == (N, M, self.units * 3)

        # (N, M, state_dim) => (N, M, units)
        state_features = self.state_layers(states)
        # state_features = self.state_layers(states * torch.tensor([[[1., 0.]]], device=states.device))
        assert state_features.shape == (N, M, self.units)

        # (N, M, units)
        merged_features = torch.cat(
            (observation_features, state_features),
            dim=2)
        assert merged_features.shape == (N, M, self.units * 4)

        # (N, M, units * 4) => (N, M, 1)
        log_likelihoods = self.shared_layers(merged_features)
        assert log_likelihoods.shape == (N, M, 1)

        # Return (N, M)
        return torch.squeeze(log_likelihoods, dim=2)
