from django.shortcuts import render
from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse
from .models import Usuario

def index(request):
    context={
        "page_title":"Dashboard"
    }
    return render(request,'fillow/index.html',context)


def index_2(request):
    context={
        "page_title":"Dashboard"
    }
    return render(request,'fillow/index-2.html',context)


def project_page(request):
    context={
        "page_title":"Project"
    }
    return render(request,'fillow/project-page.html',context)


def contacts(request):
    context={
        "page_title":"Contacts"
    }
    return render(request,'fillow/contacts.html',context)


def kanban(request):
    context={
        "page_title":"Kanban"
    }
    return render(request,'fillow/kanban.html',context)


def calendar_page(request):
    context={
        "page_title":"Calendar Page"
    }
    return render(request,'fillow/calendar-page.html',context)


def message(request):
    context={
        "page_title":"Message"
    }
    return render(request,'fillow/message.html',context)


def content(request):
    context={
        "page_title":"Content"
    }
    return render(request,'fillow/cms/content.html',context)


def add_content(request):
    context={
        "page_title":"Add Content"
    }
    return render(request,'fillow/cms/add-content.html',context)


def menu(request):
    context={
        "page_title":"Menu"
    }
    return render(request,'fillow/cms/menu.html',context)


def email_template(request):
    context={
        "page_title":"Email Template"
    }
    return render(request,'fillow/cms/email-template.html',context)


def add_email(request):
    context={
        "page_title":"Add Email"
    }
    return render(request,'fillow/cms/add-email.html',context)


def blog(request):
    context={
        "page_title":"Blog"
    }
    return render(request,'fillow/cms/blog.html',context)


def add_blog(request):
    context={
        "page_title":"Add Blog"
    }
    return render(request,'fillow/cms/add-blog.html',context)


def blog_category(request):
    context={
        "page_title":"Blog Category"
    }
    return render(request,'fillow/cms/blog-category.html',context)


def app_profile(request):
    context={
        "page_title":"App Profile"
    }
    return render(request,'fillow/apps/app-profile.html',context)


def edit_profile(request):
    context={
        "page_title":"Edit Profile"
    }
    return render(request,'fillow/apps/edit-profile.html',context)


def post_details(request):
    context={
        "page_title":"Post Details"
    }
    return render(request,'fillow/apps/post-details.html',context)


def email_compose(request):
    context={
        "page_title":"Compose"
    }
    return render(request,'fillow/apps/email/email-compose.html',context)


def email_inbox(request):
    context={
        "page_title":"Inbox"
    }
    return render(request,'fillow/apps/email/email-inbox.html',context)


def email_read(request):
    context={
        "page_title":"Read"
    }
    return render(request,'fillow/apps/email/email-read.html',context)


def app_calender(request):
    context={
        "page_title":"Calendar"
    }
    return render(request,'fillow/apps/app-calender.html',context)


def ecom_product_grid(request):
    context={
        "page_title":"Product Grid"
    }
    return render(request,'fillow/apps/shop/ecom-product-grid.html',context)


def ecom_product_list(request):
    context={
        "page_title":"Product List"
    }
    return render(request,'fillow/apps/shop/ecom-product-list.html',context)


def ecom_product_detail(request):
    context={
        "page_title":"Product Detail"
    }
    return render(request,'fillow/apps/shop/ecom-product-detail.html',context)


def ecom_product_order(request):
    context={
        "page_title":"Product Order"
    }
    return render(request,'fillow/apps/shop/ecom-product-order.html',context)


def ecom_checkout(request):
    context={
        "page_title":"Checkout"
    }
    return render(request,'fillow/apps/shop/ecom-checkout.html',context)


def ecom_invoice(request):
    context={
        "page_title":"Invoice"
    }
    return render(request,'fillow/apps/shop/ecom-invoice.html',context)


def ecom_customers(request):
    context={
        "page_title":"Customers"
    }
    return render(request,'fillow/apps/shop/ecom-customers.html',context)



def chart_flot(request):
    context={
        "page_title":"Chart Flot"
    }
    return render(request,'fillow/charts/chart-flot.html',context)


def chart_morris(request):
    context={
        "page_title":"Chart Morris"
    }
    return render(request,'fillow/charts/chart-morris.html',context)


def chart_chartjs(request):
    context={
        "page_title":"Chart Chartjs"
    }
    return render(request,'fillow/charts/chart-chartjs.html',context)


def chart_chartist(request):
    context={
        "page_title":"Chart Chartist"
    }
    return render(request,'fillow/charts/chart-chartist.html',context)


def chart_sparkline(request):
    context={
        "page_title":"Chart Sparkline"
    }
    return render(request,'fillow/charts/chart-sparkline.html',context)


def chart_peity(request):
    context={
        "page_title":"Chart Peity"
    }
    return render(request,'fillow/charts/chart-peity.html',context)



def ui_accordion(request):
    context={
        "page_title":"Accordion"
    }
    return render(request,'fillow/bootstrap/ui-accordion.html',context)


def ui_alert(request):
    context={
        "page_title":"Alert"
    }
    return render(request,'fillow/bootstrap/ui-alert.html',context)


def ui_badge(request):
    context={
        "page_title":"Badge"
    }
    return render(request,'fillow/bootstrap/ui-badge.html',context)


def ui_button(request):
    context={
        "page_title":"Button"
    }
    return render(request,'fillow/bootstrap/ui-button.html',context)


def ui_modal(request):
    context={
        "page_title":"Modal"
    }
    return render(request,'fillow/bootstrap/ui-modal.html',context)


def ui_button_group(request):
    context={
        "page_title":"Button Group"
    }
    return render(request,'fillow/bootstrap/ui-button-group.html',context)


def ui_list_group(request):
    context={
        "page_title":"List Group"
    }
    return render(request,'fillow/bootstrap/ui-list-group.html',context)


def ui_card(request):
    context={
        "page_title":"Card"
    }
    return render(request,'fillow/bootstrap/ui-card.html',context)


def ui_carousel(request):
    context={
        "page_title":"Carousel"
    }
    return render(request,'fillow/bootstrap/ui-carousel.html',context)


def ui_dropdown(request):
    context={
        "page_title":"Dropdown"
    }
    return render(request,'fillow/bootstrap/ui-dropdown.html',context)


def ui_popover(request):
    context={
        "page_title":"Popover"
    }
    return render(request,'fillow/bootstrap/ui-popover.html',context)


def ui_progressbar(request):
    context={
        "page_title":"Progressbar"
    }
    return render(request,'fillow/bootstrap/ui-progressbar.html',context)


def ui_tab(request):
    context={
        "page_title":"Tab"
    }
    return render(request,'fillow/bootstrap/ui-tab.html',context)


def ui_typography(request):
    context={
        "page_title":"Typography"
    }
    return render(request,'fillow/bootstrap/ui-typography.html',context)


def ui_pagination(request):
    context={
        "page_title":"Pagination"
    }
    return render(request,'fillow/bootstrap/ui-pagination.html',context)


def ui_grid(request):
    context={
        "page_title":"Grid"
    }
    return render(request,'fillow/bootstrap/ui-grid.html',context)




def uc_select2(request):
    context={
        "page_title":"Select"
    }
    return render(request,'fillow/plugins/uc-select2.html',context)


def uc_nestable(request):
    context={
        "page_title":"Nestable"
    }
    return render(request,'fillow/plugins/uc-nestable.html',context)


def uc_noui_slider(request):
    context={
        "page_title":"UI Slider"
    }
    return render(request,'fillow/plugins/uc-noui-slider.html',context)


def uc_sweetalert(request):
    context={
        "page_title":"Sweet Alert"
    }
    return render(request,'fillow/plugins/uc-sweetalert.html',context)


def uc_toastr(request):
    context={
        "page_title":"Toastr"
    }
    return render(request,'fillow/plugins/uc-toastr.html',context)


def map_jqvmap(request):
    context={
        "page_title":"Jqvmap"
    }
    return render(request,'fillow/plugins/map-jqvmap.html',context)


def uc_lightgallery(request):
    context={
        "page_title":"LightGallery"
    }
    return render(request,'fillow/plugins/uc-lightgallery.html',context)


def widget_basic(request):
    context={
        "page_title":"Widget"
    }
    return render(request,'fillow/widget-basic.html',context)

def form_element(request):
    context={
        "page_title":"Form Element"
    }
    return render(request,'fillow/forms/form-element.html',context)


def form_wizard(request):
    context={
        "page_title":"Form Wizard"
    }
    return render(request,'fillow/forms/form-wizard.html',context)


def form_editor(request):
    context={
        "page_title":"CkEditor"
    }
    return render(request,'fillow/forms/form-editor.html',context)


def form_pickers(request):
    context={
        "page_title":"Pickers"
    }
    return render(request,'fillow/forms/form-pickers.html',context)


def form_validation(request):
    context={
        "page_title":"Form Validation"
    }
    return render(request,'fillow/forms/form-validation.html',context)


def table_bootstrap_basic(request):
    context={
        "page_title":"Table Bootstrap"
    }
    return render(request,'fillow/table/table-bootstrap-basic.html',context)


def table_datatable_basic(request):
    context={
        "page_title":"Table Datatable"
    }
    return render(request,'fillow/table/table-datatable-basic.html',context)






def page_register(request):
    return render(request,'fillow/pages/page-register.html')

def page_login(request):
    if request.method == 'POST':
        # Obter o nome de usuário ou email e a senha do formulário
        username_or_email = request.POST.get('username')
        password = request.POST.get('password')

        # Autenticar o usuário
        user = authenticate(request, username=username_or_email, password=password)

        if user is not None:
            # Verifica se o usuário está aprovado (caso exista) ou se é superuser
            if getattr(user, 'aprovado', False) or user.is_superuser:
                login(request, user)
                return redirect(reverse('fillow:index'))  # Redirecione para a página desejada após o login
            else:
                messages.error(request, 'Sua conta ainda não foi aprovada para login.')
        else:
            messages.error(request, 'Credenciais inválidas. Verifique o nome de usuário/email e senha.')

    return render(request, 'fillow/pages/page-login.html')


def page_forgot_password(request):
    return render(request,'fillow/pages/page-forgot-password.html')

def page_lock_screen(request):
    return render(request,'fillow/pages/page-lock-screen.html')

def page_empty(request):
    context={
        "page_title":"Empty Page"
    }
    return render(request,'fillow/pages/page-empty.html',context)

def page_error_400(request):
    return render(request,'400.html')
    
def page_error_403(request):
    return render(request,'403.html')

def page_error_404(request):
    return render(request,'404.html')

def page_error_500(request):
    return render(request,'500.html')

def page_error_503(request):
    return render(request,'503.html')
    













