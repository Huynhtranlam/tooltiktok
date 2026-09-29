# LiveLedger — phân ca đơn live TikTok

Ứng dụng nhiều máy cho lịch livestream, nhập CSV đơn hàng, đối soát đơn theo giờ tạo và chốt hoa hồng. Mọi trình duyệt truy cập **cùng một địa chỉ máy chủ** và dùng chung một cơ sở dữ liệu SQLite trên máy chủ. Mã nguồn trên GitHub không chứa dữ liệu đơn hàng.

## Chạy thử trên một máy

Cần Python 3.12+. Trong PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:TOOLTIKTOK_SECRET_KEY = python -c "import secrets;print(secrets.token_hex(32))"
python app.py init-admin --username owner
python app.py serve --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000/` và đăng nhập bằng tài khoản vừa tạo. Giữ nguyên `TOOLTIKTOK_SECRET_KEY` qua mỗi lần chạy bằng biến môi trường của máy chủ; đổi khóa sẽ làm các phiên đăng nhập cũ hết hiệu lực. Thư mục `data/` giữ cơ sở dữ liệu và bản sao lưu; không đưa thư mục này lên GitHub.

**Không mở `index.html` trực tiếp bằng `file://` ở phiên bản mới.** Trang mới phải đi qua máy chủ để các máy cùng thấy một lịch và đơn hàng.
GitHub chỉ giữ mã nguồn; GitHub Pages không chạy được Python/SQLite của bản dùng chung. Sau khi đẩy mã lên GitHub vẫn cần chạy máy chủ riêng như phần dưới.

## Đưa lên Internet với HTTPS

Cần một máy chủ có Docker, một tên miền trỏ tới máy chủ và cổng 80/443. Sao chép `.env.example` thành `.env`, đặt `DOMAIN` và một `TOOLTIKTOK_SECRET_KEY` ngẫu nhiên dài. Sau đó:

```bash
docker compose -f compose.production.yml up -d --build
docker compose -f compose.production.yml exec app python app.py init-admin --username owner
```

Caddy cấp HTTPS cho tên miền và chuyển yêu cầu tới ứng dụng. Không công khai cổng 8000 trực tiếp. Dữ liệu nằm trong volume `app_data`; cần sao lưu volume này ra nơi khác. Máy chủ chỉ nên chạy **một bản ứng dụng** dùng một file SQLite. Nếu sau này cần nhiều máy chủ hoặc tải lớn hơn, chuyển cơ sở dữ liệu sang PostgreSQL trước khi nhân bản ứng dụng.

Nếu chỉ chạy trong mạng cửa hàng, có thể dùng một máy chủ nội bộ và truy cập bằng IP của nó. Trên mạng nội bộ tin cậy, chạy `python app.py serve --host 0.0.0.0 --port 8000`; để truy cập qua Internet vẫn cần HTTPS và tên miền như trên.

## Chuyển dữ liệu từ công cụ HTML cũ

1. Trên **từng máy/trình duyệt đã dùng**, mở đúng file HTML cũ ở đúng địa chỉ trước đây. Vào **Thiết lập → Sao lưu dữ liệu** để tải JSON. File `legacy.html` trong repo là bản mã cũ để đối chiếu, nhưng đổi đường dẫn file có thể không thấy dữ liệu của đường dẫn ban đầu.
2. Trong LiveLedger mới, đăng nhập quản lý, vào **Thiết lập → Nhập từ công cụ HTML cũ**, chọn JSON và **Xem trước**. Màn hình sẽ báo số đơn trùng với máy chủ.
3. Nếu lịch trong JSON là lịch muốn dùng, đánh dấu **Thay lịch, lịch riêng và tỷ lệ**. Nếu khoảng lịch thứ ba trước đây chưa lưu được, giữ **bỏ đánh dấu** để dùng ba khoảng đã được khởi tạo từ ảnh 01/09–04/10/2026, rồi kiểm tra từng khoảng trong màn **Lịch live**.
4. Chuyển lần lượt các bản sao lưu còn lại. Đơn cùng mã sẽ được cập nhật theo file nhập sau; vì vậy cần đối chiếu các file có đơn trùng trước khi hoàn tất. Máy chủ tự tạo bản sao lưu SQLite trước mỗi lần chuyển JSON.

Đừng xóa dữ liệu ở công cụ cũ cho đến khi đã so sánh số đơn, lịch, tỷ lệ và báo cáo ở máy chủ mới.

## Các màn hình và quy tắc

- **Tổng quan:** lọc khoảng ngày, xem đơn/sản phẩm/doanh số/hoa hồng, biểu đồ sản phẩm theo nhân viên. Nhập CSV có bước xem trước số đơn mới, đơn cập nhật và dòng lỗi; file có lỗi sẽ không được ghi.
- **Lịch live:** sửa từng khoảng ngày; chọn nhân viên, giờ và phút bằng danh sách 24 giờ; chọn rõ **Hôm nay/Hôm sau** cho giờ kết thúc. Ca chồng giờ hoặc khoảng ngày chồng nhau không thể lưu. Bản nháp tự lưu trên máy chủ theo tài khoản và có thể mở lại sau khi tải trang.
- **Đổi ca một ngày:** lịch riêng của ngày đó được ưu tiên hơn lịch cố định, và có thể bỏ để quay về lịch cố định.
- **Đơn hàng:** xem tất cả đơn và lý do gán. Quản lý có thể sửa gán của đơn LIVE kèm lý do; đơn hủy/hoàn hoặc ngoài LIVE không thể gán hoa hồng.
- **Hoa hồng:** tỷ lệ có ngày hiệu lực theo ngày tạo đơn. Có thể chốt kỳ khi không còn đơn LIVE chưa gán. Kết quả kỳ đã chốt là bản chụp cố định; mở lại kỳ phải ghi lý do.
- **Thiết lập:** tạo nhân viên, tài khoản quản lý/chỉ xem, tải bản sao lưu, nhập dữ liệu cũ và xem lịch sử thay đổi.

Đơn được gán theo cột `Created Time` của CSV, dạng ngày/tháng/năm và giờ:phút[:giây]. Giờ kết thúc ca **không** tính vào ca: HÀO 21:00 hôm nay đến 01:00 hôm sau nhận đơn 00:59:59, còn 01:00:00 ở ngoài ca. Doanh số tạm tính lấy từ `SKU Subtotal After Discount`; hoa hồng tạm tính bằng doanh số của từng dòng nhân tỷ lệ hiệu lực. Đơn có trạng thái hủy/hoàn hoặc tiền hoàn dương bị loại khỏi hoa hồng. Cần thống nhất quy tắc làm tròn và điều chỉnh hoàn tiền thực tế trước khi dùng kết quả như số thanh toán cuối cùng.

## Sao lưu và vận hành

Ứng dụng tạo tối đa 30 bản sao lưu SQLite gần nhất trong `data/backups` (một bản khi khởi động mỗi ngày và một bản trước mỗi lần nhập JSON cũ). Quản lý có thể tạo thêm ở **Thiết lập** hoặc chạy `python app.py backup`. Hãy sao chép các bản sao lưu sang ổ hoặc dịch vụ khác; bản sao lưu cùng ổ không bảo vệ khỏi hỏng ổ. Nút **Tải bản sao lưu** xuất JSON để kiểm tra và lưu trữ; thao tác khôi phục đầy đủ từ JSON máy chủ chưa được mở trong giao diện, hãy dùng bản SQLite và quy trình vận hành máy chủ để phục hồi.

CSV chỉ được đọc các cột cần báo cáo; tên, số điện thoại và địa chỉ khách hàng trong file gốc không được lưu. API yêu cầu đăng nhập; thao tác sửa cần quyền quản lý và mã chống gửi yêu cầu giả. Khi triển khai Internet, luôn dùng HTTPS và giữ kín `.env` cùng thư mục dữ liệu.

## Kiểm thử

```powershell
pip install pytest
python -m pytest -q
node --check app.js
```

Các kiểm thử bao phủ gán ca qua nửa đêm, chặn ca chồng giờ, chia sẻ lịch giữa hai trình duyệt, nhập CSV, gán tay, kỳ đã chốt và chuyển bản sao lưu cũ.
