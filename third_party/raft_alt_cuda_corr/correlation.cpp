#include <torch/extension.h>
#include <vector>

// CUDA forward declarations
std::vector<torch::Tensor> corr_cuda_forward(
    torch::Tensor fmap1,
    torch::Tensor fmap2,
    torch::Tensor coords,
    int radius);

std::vector<torch::Tensor> corr_cuda_backward(
  torch::Tensor fmap1,
  torch::Tensor fmap2,
  torch::Tensor coords,
  torch::Tensor corr_grad,
  int radius);

// C++ interface
#define CHECK_CUDA(x) TORCH_CHECK(x.is_cuda(), #x " must be a CUDA tensor")
#define CHECK_CONTIGUOUS(x) TORCH_CHECK(x.is_contiguous(), #x " must be contiguous")
#define CHECK_INPUT(x) CHECK_CUDA(x); CHECK_CONTIGUOUS(x)

std::vector<torch::Tensor> corr_forward(
    torch::Tensor fmap1,
    torch::Tensor fmap2,
    torch::Tensor coords,
    int radius) {
  CHECK_INPUT(fmap1);
  CHECK_INPUT(fmap2);
  CHECK_INPUT(coords);

  TORCH_CHECK(fmap1.scalar_type() == torch::kFloat32 && fmap2.scalar_type() == torch::kFloat32 && coords.scalar_type() == torch::kFloat32,
              "alt_cuda_corr requires float32 inputs");
  TORCH_CHECK(fmap1.dim() == 4 && fmap2.dim() == 4 && coords.dim() == 5, "Invalid correlation input dimensions");
  TORCH_CHECK(fmap1.device() == fmap2.device() && fmap1.device() == coords.device(), "All inputs must use the same CUDA device");
  TORCH_CHECK(radius >= 0 && radius <= 8, "Radius must be between 0 and 8");
  TORCH_CHECK(fmap1.size(0) > 0 && fmap1.size(1) > 0 && fmap1.size(2) > 0 && fmap2.size(1) > 0 && fmap2.size(2) > 0,
              "Empty feature maps are unsupported");
  TORCH_CHECK(fmap1.size(0) == fmap2.size(0) && fmap1.size(3) == fmap2.size(3), "Feature batch/channel dimensions must match");
  TORCH_CHECK(fmap1.size(3) > 0 && fmap1.size(3) % 32 == 0, "Feature channels must be a positive multiple of 32");
  TORCH_CHECK(coords.size(0) == fmap1.size(0) && coords.size(1) == 1 && coords.size(2) == fmap1.size(1) &&
              coords.size(3) == fmap1.size(2) && coords.size(4) == 2, "Coordinates must have shape B,1,H,W,2");

  return corr_cuda_forward(fmap1, fmap2, coords, radius);
}


std::vector<torch::Tensor> corr_backward(
    torch::Tensor fmap1,
    torch::Tensor fmap2,
    torch::Tensor coords,
    torch::Tensor corr_grad,
    int radius) {
  CHECK_INPUT(fmap1);
  CHECK_INPUT(fmap2);
  CHECK_INPUT(coords);
  CHECK_INPUT(corr_grad);

  return corr_cuda_backward(fmap1, fmap2, coords, corr_grad, radius);
}


PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
  m.def("forward", &corr_forward, "CORR forward");
  m.attr("reezsynth_build") = "0.2.0";
}
