import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import convolve
from scipy.stats import norm
from numpy.polynomial import chebyshev
from .data_io import DataIO

class UniversalEngine:
    """
    CAESAR Pro Core Analysis Engine (Phase 2.6 — Refactored)

    Responsibilities
    ----------------
    - Stores and pre-processes reference cross-section spectra (one per gas).
    - Exposes fast interpolators so the worker can shift/squeeze each reference
      during the non-linear optimization without re-reading files.
    - Provides two mathematical interfaces for the fitting loop:
        get_model_components()  — evaluates the full model given known parameters
        get_basis_matrix()      — assembles the matrix A so that the linear
                                  coefficients can be solved via least squares (A·c = y)

    Key concepts
    ------------
    Shift   : A small wavelength offset (in pixels) that corrects for temperature
              or mechanical drift of the spectrometer grating.
    Squeeze : A small wavelength stretch factor that corrects for dispersion changes
              (e.g., 1.001 means the spectrum is 0.1% wider than the reference).
    ILS     : Instrument Line Shape — the Gaussian blurring imposed by the finite
              slit width of the spectrometer.  We convolve references with a matching
              Gaussian so they look the same as measured spectra.
    Etalon  : Sinusoidal interference fringes caused by partial reflections inside
              the optical cavity.  Modelled as  A·sin(freq·x + phase).
    Baseline: A Chebyshev polynomial that accounts for the slowly varying broadband
              background (lamp emission, scattering continuum, etc.).
    """

    def __init__(self):
        # raw_references: name → 1-D numpy array of the original cross-section values
        self.raw_references = {}

        # interpolators: name → scipy interp1d object that lets us evaluate the
        # reference at non-integer (shifted/squeezed) pixel positions
        self.interpolators = {}

        # gas_list: ordered list of gas names, e.g. ['NO2', 'H2O', 'O4']
        # The order here matches the order of coefficients in fit results.
        self.gas_list = []

        # scaling_factors: name → peak absolute value of the reference (after multiplier).
        # We divide each reference by this before fitting so that all species
        # live on a similar numerical scale, which improves optimizer stability.
        self.scaling_factors = {}

        # multipliers: name → the scale multiplier applied when loading (10^exponent).
        # Needed to back-convert fit coefficients to physical concentrations.
        # The normalised reference column = ref_raw / max(ref_raw), so the multiplier
        # cancels in the column but must be re-applied in the concentration formula:
        #   N [cm-3] = (coeff / scale_factor) / max(ref_raw)
        #            = (coeff / scale_factor) / (scaling_factors[name] / multipliers[name])
        #            = (coeff / scale_factor) * multipliers[name] / scaling_factors[name]
        self.multipliers = {}

        # Wavelength axis in nm (set once, shared by all references)
        self._wave_axis = None

    def clear_engine(self):
        """Resets the engine to a blank state (called before re-locking references)."""
        self.raw_references = {}
        self.interpolators = {}
        self.gas_list = []
        self.scaling_factors = {}
        self.multipliers = {}
        self._wave_axis = None

    def set_wavelength_axis(self, wave_nm):
        """Stores the wavelength calibration array (pixel index → nm)."""
        self._wave_axis = np.array(wave_nm)

    def pixel_to_wavelength(self, pixel_idx):
        """
        Converts pixel indices to wavelengths (nm) using the loaded calibration.
        Falls back to returning the pixel indices unchanged if no calibration is loaded.
        """
        if self._wave_axis is not None:
            # Build a linear interpolator from pixel index to nm
            f = interp1d(
                np.arange(len(self._wave_axis)), self._wave_axis,
                kind='linear', bounds_error=False, fill_value='extrapolate'
            )
            return f(np.asarray(pixel_idx, dtype=float))
        # No calibration — return pixel numbers as-is
        return np.asarray(pixel_idx, dtype=float)

    def is_engine_ready(self) -> bool:
        """Returns True when at least one reference has been locked in."""
        return len(self.gas_list) > 0

    # ─────────────────────────────────────────────────────────────────────────
    # Reference Loading & Pre-processing
    # ─────────────────────────────────────────────────────────────────────────

    def add_reference(self, name, filepath, wave_nm=None, multiplier=1.0):
        """
        Loads one gas cross-section file and registers it with the engine.

        Steps
        -----
        1. Load raw (wavelength, intensity) from file via DataIO.
        2. If the reference has its own wavelength grid (e.g., HITRAN 0.01 nm spacing),
           interpolate it onto the instrument's wavelength axis.
        3. Apply the user-supplied multiplier (powers of 10 to fix unit scale).
        4. Store the processed array in raw_references and build an interpolator
           so the optimizer can evaluate the reference at non-integer pixel positions.
        5. Record the peak absolute value as the scaling_factor for normalization.

        Returns (True, message) on success, (False, error_message) on failure.
        """
        try:
            wave_nm_clean = DataIO.enforce_1d_array(wave_nm)
            wave_nm_ref, intensity_raw = DataIO.load_reference(filepath)

            if wave_nm_ref is not None and wave_nm_clean is not None:
                # Reference has its own dense wavelength grid → resample onto ours
                f_interp = interp1d(
                    wave_nm_ref, intensity_raw,
                    kind='cubic', bounds_error=False, fill_value="extrapolate"
                )
                intensity_processed = f_interp(wave_nm_clean)
                print(f"-> {name}: Interpolated to instrument wavelength.")
            else:
                # No wavelength data — assume the reference pixel grid already matches
                intensity_processed = intensity_raw
                print(f"-> {name}: No wavelength info. Loaded as 1D array.")

            # Apply the scale multiplier (e.g., 1e-19 for cm² cross-sections)
            intensity_processed = intensity_processed * multiplier

            # Store the peak magnitude for normalization during fitting
            max_abs_val = np.max(np.abs(intensity_processed))
            if max_abs_val == 0:
                max_abs_val = 1.0  # Avoid division by zero

            self.raw_references[name] = intensity_processed

            # Build a cubic interpolator indexed by pixel number
            pixel_idx = np.arange(len(intensity_processed))
            self.interpolators[name] = interp1d(
                pixel_idx, intensity_processed,
                kind='cubic', bounds_error=False, fill_value="extrapolate"
            )

            if name not in self.gas_list:
                self.gas_list.append(name)

            self.scaling_factors[name] = max_abs_val
            self.multipliers[name] = multiplier
            return True, f"{name} Loaded Successfully"

        except Exception as e:
            return False, f"Error loading {name}: {str(e)}"

    def apply_ils_convolution(self, fwhm_gaussian, fwhm_lorentzian=0.0):
        """
        Blurs all loaded references with a Voigt (or pure Gaussian) ILS kernel.

        fwhm_gaussian:   Gaussian FWHM in pixels (instrument slit broadening)
        fwhm_lorentzian: Lorentzian FWHM in pixels (optical aberrations, scattering)
                         0.0 → pure Gaussian (original behaviour preserved exactly)

        If both are effectively zero (≤ 0.1), the convolution is skipped and
        interpolators are rebuilt directly from the raw arrays.
        """
        from scipy.special import voigt_profile

        if not self.is_engine_ready():
            return

        if fwhm_gaussian <= 0.1 and fwhm_lorentzian <= 0.1:
            for name in self.gas_list:
                pixel_idx = np.arange(len(self.raw_references[name]))
                self.interpolators[name] = interp1d(
                    pixel_idx, self.raw_references[name],
                    kind='cubic', fill_value="extrapolate"
                )
            return

        sigma_g = fwhm_gaussian / 2.3548
        gamma_l = fwhm_lorentzian / 2.0

        # Truncate at 4σ_G or 10γ_L (whichever is larger) to capture tails
        radius = max(int(4 * sigma_g) + 1, int(10 * gamma_l) + 1)
        x_kernel = np.arange(-radius, radius + 1, dtype=float)

        if fwhm_lorentzian <= 0.1:
            # Pure Gaussian — identical numerical result to the old code
            kernel = norm.pdf(x_kernel, 0, sigma_g)
        else:
            # Voigt profile: Gaussian ⊗ Lorentzian
            kernel = voigt_profile(x_kernel, sigma_g, gamma_l)

        kernel /= kernel.sum()

        for name in self.gas_list:
            convolved_y = convolve(self.raw_references[name], kernel, mode='same')
            pixel_idx = np.arange(len(self.raw_references[name]))
            self.interpolators[name] = interp1d(
                pixel_idx, convolved_y,
                kind='cubic', fill_value="extrapolate"
            )
            max_abs_val = np.max(np.abs(convolved_y))
            self.scaling_factors[name] = max_abs_val if max_abs_val != 0 else 1.0

    def apply_manual_mask(self, name, min_idx, max_idx):
        """
        Zeroes out everything outside [min_idx, max_idx] in the reference.

        Masking is used to suppress noisy or irrelevant spectral regions
        (e.g., detector edge artifacts, saturated lines) so the fit focuses
        only on the clean absorption features.
        """
        if name not in self.raw_references:
            return False
        data = self.raw_references[name].copy()
        start, end = max(0, int(min_idx)), min(len(data), int(max_idx))
        data[:start], data[end:] = 0.0, 0.0   # Zero everything outside the window
        self._sync_reference_update(name, data)
        return True

    def apply_auto_mask(self, name, threshold_percent):
        """
        Sets to zero any part of the reference below threshold_percent of its peak.

        Useful for removing weak, noisy tails at the edges of an absorption band
        without manually specifying pixel indices.
        """
        if name not in self.raw_references:
            return False
        data = self.raw_references[name].copy()
        max_val = np.max(np.abs(data))
        if max_val == 0:
            return False
        # Zero out everything below the threshold fraction of the peak
        data[np.abs(data) < max_val * (threshold_percent / 100.0)] = 0.0
        self._sync_reference_update(name, data)
        return True

    def _sync_reference_update(self, name, data):
        """
        Internal helper: saves modified reference data and rebuilds its interpolator.
        Called after any masking operation to keep raw_references and interpolators in sync.
        """
        self.raw_references[name] = data
        pixel_idx = np.arange(len(data))
        self.interpolators[name] = interp1d(
            pixel_idx, data, kind='cubic', fill_value="extrapolate"
        )
        max_abs_val = np.max(np.abs(data))
        self.scaling_factors[name] = max_abs_val if max_abs_val != 0 else 1.0

    # ─────────────────────────────────────────────────────────────────────────
    # Mathematical Fitting Models
    # ─────────────────────────────────────────────────────────────────────────

    def get_model_components(
        self, pixel_idx, shifts, squeezes, gas_coeffs, poly_coeffs,
        etalon_amp=0.0, etalon_freq=0.0, etalon_phase=0.0,
        custom_basis=None, custom_coeffs=None
    ):
        """
        Evaluates the full spectral model and returns each component separately.

        The DOAS/BBCEAS spectral model is:
            y_model = baseline(x) + Σ[coeff_i · ref_i(x)] + etalon(x) + custom(x)

        Where:
          - ref_i(x) is the i-th reference cross-section evaluated at shifted/squeezed
            pixel positions  x_shifted = (x - center) * squeeze + center + shift
          - baseline is a Chebyshev polynomial mapped to [-1, 1] over the fit window
          - etalon is a sinusoidal fringe:  A · sin(freq·x + phase)
          - custom covers optional ring effect or PCA-background terms

        Returns:
          (full_model, total_absorption, baseline, etalon_wave, custom_effect)
        """
        # Use the middle pixel as the squeeze/shift center to minimize correlation
        center_idx = pixel_idx[len(pixel_idx) // 2]

        # ── Gas absorption sum ───────────────────────────────────────────────
        total_absorption = 0
        for i, name in enumerate(self.gas_list):
            sh = shifts[i]   if hasattr(shifts,   '__iter__') else shifts
            sq = squeezes[i] if hasattr(squeezes, '__iter__') else squeezes

            # Apply shift and squeeze: move each pixel by 'sh' and stretch by 'sq'
            pixel_shifted = (pixel_idx - center_idx) * sq + center_idx + sh

            # Normalize by the peak magnitude so every gas starts near scale 1
            normalized_ref = self.interpolators[name](pixel_shifted) / self.scaling_factors[name]
            total_absorption += gas_coeffs[i] * normalized_ref

        # ── Chebyshev polynomial baseline ────────────────────────────────────
        # Map pixel range to [-1, 1] for numerical stability of Chebyshev polynomials
        baseline = 0
        if len(poly_coeffs) > 0:
            x_min, x_max = pixel_idx[0], pixel_idx[-1]
            x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0
            baseline = chebyshev.chebval(x_mapped, poly_coeffs)

        # ── Etalon fringe ────────────────────────────────────────────────────
        etalon_wave = etalon_amp * np.sin(etalon_freq * pixel_idx + etalon_phase)

        # ── Custom optical correction terms (Ring Effect, PCA background, etc.) ──
        custom_effect = 0
        if custom_basis is not None and custom_coeffs is not None:
            # custom_basis is a 2D array of shape (n_pixels, n_bases)
            for i in range(custom_basis.shape[1]):
                custom_effect += custom_coeffs[i] * custom_basis[:, i]

        full_model = baseline + total_absorption + etalon_wave + custom_effect
        return full_model, total_absorption, baseline, etalon_wave, custom_effect

    def get_individual_gas_contribution(self, pixel_idx, shifts, squeezes, gas_coeffs, gas_index):
        """
        Returns the spectral contribution of a single gas at index gas_index.
        Used by the monitor to draw each gas component separately on the graph.
        """
        center_idx = pixel_idx[len(pixel_idx) // 2]
        sh = shifts[gas_index]   if hasattr(shifts,   '__iter__') else shifts
        sq = squeezes[gas_index] if hasattr(squeezes, '__iter__') else squeezes

        pixel_shifted = (pixel_idx - center_idx) * sq + center_idx + sh
        gas_name    = self.gas_list[gas_index]
        coefficient = gas_coeffs[gas_index]

        return (
            coefficient
            * self.interpolators[gas_name](pixel_shifted)
            / self.scaling_factors[gas_name]
        )

    def get_basis_matrix(
        self, pixel_idx, shifts, squeezes,
        poly_order=-1, etalon_freq=None, etalon_phase=0.0, custom_basis=None
    ):
        """
        Builds the design matrix A for the linear least-squares problem  A · c = y.

        Each column of A is one model component evaluated at pixel_idx:
          columns 0 … N_gas-1       : shifted/squeezed reference spectra (normalized)
          columns N_gas … N_gas+P   : Chebyshev polynomial basis vectors (if poly_order ≥ 0)
          column  N_gas+P+1          : etalon sine wave (if etalon_freq is given)
          remaining columns           : custom basis vectors (Ring, PCA, etc.)

        Solving  A · c = y  via least squares gives the optimal linear coefficients
        (gas concentrations, polynomial coefficients, etalon amplitude) in one shot.
        This is the 'linear sub-problem' of the VarPro algorithm used in the worker.
        """
        center_idx = pixel_idx[len(pixel_idx) // 2]
        column_vectors = []

        # ── 1. Trace gas columns ─────────────────────────────────────────────
        for i, name in enumerate(self.gas_list):
            sh = shifts[i]   if hasattr(shifts,   '__iter__') else shifts
            sq = squeezes[i] if hasattr(squeezes, '__iter__') else squeezes

            pixel_shifted = (pixel_idx - center_idx) * sq + center_idx + sh
            column_vectors.append(
                self.interpolators[name](pixel_shifted) / self.scaling_factors[name]
            )

        # ── 2. Chebyshev polynomial baseline ────────────────────────────────
        if poly_order >= 0:
            x_min, x_max = pixel_idx[0], pixel_idx[-1]
            x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0
            # chebvander returns the full Vandermonde matrix: one column per degree 0..poly_order
            vander_matrix = chebyshev.chebvander(x_mapped, poly_order)
            for i in range(poly_order + 1):
                column_vectors.append(vander_matrix[:, i])

        # ── 3. Etalon interference fringe ────────────────────────────────────
        if etalon_freq is not None:
            column_vectors.append(np.sin(etalon_freq * pixel_idx + etalon_phase))

        # ── 4. Custom optical correction terms (Ring Effect, PCA Background, etc.) ──
        if custom_basis is not None:
            if custom_basis.ndim == 1:
                custom_basis = custom_basis.reshape(-1, 1)  # Ensure 2-D for the loop below
            for i in range(custom_basis.shape[1]):
                column_vectors.append(custom_basis[:, i])

        # Stack all columns into an (n_pixels × n_params) matrix
        return np.column_stack(column_vectors)
